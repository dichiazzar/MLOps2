"""Middleware ASGI de seguridad para la API REST (clase 7, SAIF).

Envuelve la API de MLOps1_final SIN modificarla:
  - /health, /docs y /openapi.json son públicas (en REST el contrato es público a propósito).
  - Todo lo demás exige `Authorization: Bearer <jwt>` (401) y un rol con permiso (403).
  - POST /predict: límite por usuario (429), body <= 16 KB (413) y validación estricta del
    auto con los rangos de entrenamiento (422) ANTES de llegar a la API.
  - Cada pedido no público queda en la auditoría (usuario, acción, código, hash de la entrada).
"""

import json

from starlette.responses import JSONResponse

from app.seguridad import EntradaInvalida, TokenInvalido, autorizado, validar_auto, verificar_token

PUBLICAS = {("GET", "/health"), ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/docs/oauth2-redirect")}
ACCIONES = {
    ("POST", "/predict"): "predecir",
    ("GET", "/model/info"): "ver_modelo",
    ("GET", "/predictions/recent"): "ver_predicciones_de_otros",
}
MAX_BODY = 16 * 1024


async def _leer_cuerpo(receive, maximo):
    partes, total = [], 0
    while True:
        msg = await receive()
        if msg["type"] != "http.request":
            break
        partes.append(msg.get("body", b""))
        total += len(partes[-1])
        if total > maximo:
            return b"", True
        if not msg.get("more_body"):
            break
    return b"".join(partes), False


def _receive_con(cuerpo, original):
    """Devuelve el cuerpo ya leído a la API, y después sigue con el receive original."""
    enviado = False

    async def receive():
        nonlocal enviado
        if not enviado:
            enviado = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}
        return await original()

    return receive


class SeguridadREST:
    def __init__(self, app, auditor, limite, rangos=lambda: None, version=lambda: None):
        self.app, self.auditor, self.limite = app, auditor, limite
        self.rangos, self.version = rangos, version

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":                       # lifespan (startup de la API), etc.
            return await self.app(scope, receive, send)
        metodo, ruta = scope["method"], scope["path"]
        if (metodo, ruta) in PUBLICAS:
            return await self.app(scope, receive, send)
        accion = ACCIONES.get((metodo, ruta), "desconocida")

        headers = dict(scope.get("headers") or [])
        try:
            ident = verificar_token(headers.get(b"authorization", b"").decode("latin-1"))
        except TokenInvalido as e:
            return await self._cortar(scope, receive, send, 401, str(e), None, accion,
                                      {"WWW-Authenticate": "Bearer"})
        if accion != "desconocida" and not autorizado(ident, accion):
            return await self._cortar(scope, receive, send, 403, "rol sin permiso", ident, accion)

        cuerpo = None
        if accion == "predecir":
            if not self.limite.permitir(ident.usuario):
                return await self._cortar(scope, receive, send, 429, "demasiadas solicitudes", ident, accion)
            cuerpo, demasiado = await _leer_cuerpo(receive, MAX_BODY)
            if demasiado:
                return await self._cortar(scope, receive, send, 413, f"el cuerpo supera {MAX_BODY} bytes",
                                          ident, accion)
            try:
                validar_auto(json.loads(cuerpo or b"null"), self.rangos())
            except ValueError as e:   # EntradaInvalida y JSONDecodeError son ValueError
                return await self._cortar(scope, receive, send, 422, str(e), ident, accion, entrada=cuerpo)
            receive = _receive_con(cuerpo, receive)

        estado = {}

        async def send_espia(msg):
            if msg["type"] == "http.response.start":
                estado["codigo"] = msg["status"]
            await send(msg)

        await self.app(scope, receive, send_espia)
        self.auditor.registrar(ident, accion, estado.get("codigo"), entrada=cuerpo,
                               model_version=self.version())

    async def _cortar(self, scope, receive, send, codigo, detalle, ident, accion, headers=None, entrada=None):
        self.auditor.registrar(ident, accion, codigo, entrada=entrada, detalle=detalle,
                               model_version=self.version())
        await JSONResponse({"detail": detalle}, status_code=codigo, headers=headers)(scope, receive, send)
