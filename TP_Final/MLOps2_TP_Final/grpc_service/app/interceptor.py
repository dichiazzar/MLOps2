"""Interceptor de gRPC (clase 7): verifica el JWT de la metadata, el rol y audita cada llamada.

Mismos tokens y roles que REST y GraphQL (coherencia de controles, SAIF). El rechazo se
arma con el mismo tipo de handler que el método (unario o con streaming de respuesta).
"""

import grpc

from app.seguridad import TokenInvalido, autorizado, verificar_token


class InterceptorJWT(grpc.ServerInterceptor):
    def __init__(self, auditor, version=lambda: None):
        self.auditor, self.version = auditor, version

    def intercept_service(self, continuation, hcd):
        metodo = hcd.method.rsplit("/", 1)[-1]
        handler = continuation(hcd)
        if handler is None:
            return None
        md = dict(hcd.invocation_metadata or [])
        try:
            ident = verificar_token(md.get("authorization"))
        except TokenInvalido as e:
            return self._rechazo(handler, metodo, grpc.StatusCode.UNAUTHENTICATED, str(e), None)
        if not autorizado(ident, "predecir"):
            return self._rechazo(handler, metodo, grpc.StatusCode.PERMISSION_DENIED, "rol sin permiso", ident)
        return self._auditado(handler, metodo, ident)

    def _rechazo(self, handler, metodo, codigo, motivo, ident):
        def abortar(req, ctx):
            self.auditor.registrar(ident, metodo, codigo.name, detalle=motivo, model_version=self.version())
            ctx.abort(codigo, motivo)

        if handler.unary_stream:
            def abortar_stream(req, ctx):
                abortar(req, ctx)
                yield  # nunca se llega: abort levanta
            return grpc.unary_stream_rpc_method_handler(abortar_stream)
        return grpc.unary_unary_rpc_method_handler(abortar)

    def _auditado(self, handler, metodo, ident):
        def registrar(req, ctx, error=None):
            codigo = "OK" if error is None else (ctx.code().name if ctx.code() else "UNKNOWN")
            det = ctx.details() if error is not None else None
            det = det.decode() if isinstance(det, bytes) else det
            self.auditor.registrar(ident, metodo, codigo, entrada=req.SerializeToString(), detalle=det,
                                   model_version=self.version())

        if handler.unary_unary:
            def unario(req, ctx):
                try:
                    resp = handler.unary_unary(req, ctx)
                except Exception as e:
                    registrar(req, ctx, e)
                    raise
                if ctx.code() not in (None, grpc.StatusCode.OK):   # el servicio puso un código de error
                    registrar(req, ctx, True)
                else:
                    registrar(req, ctx)
                return resp
            return grpc.unary_unary_rpc_method_handler(unario, request_deserializer=handler.request_deserializer,
                                                       response_serializer=handler.response_serializer)
        if handler.unary_stream:
            def stream(req, ctx):
                try:
                    yield from handler.unary_stream(req, ctx)
                except Exception as e:
                    registrar(req, ctx, e)
                    raise
                registrar(req, ctx, True if ctx.code() not in (None, grpc.StatusCode.OK) else None)
            return grpc.unary_stream_rpc_method_handler(stream, request_deserializer=handler.request_deserializer,
                                                        response_serializer=handler.response_serializer)
        return handler
