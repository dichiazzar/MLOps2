from concurrent import futures

import grpc
import pytest

import car_price_pb2 as pb
import car_price_pb2_grpc as pbg
from app import seguridad as s
from app.interceptor import InterceptorJWT

AUTO = dict(name="Maruti Swift Dzire VDI", year=2014, km_driven=145500, fuel="Diesel",
            seller_type="Individual", transmission="Manual", owner="First Owner",
            mileage="23.4 kmpl", engine="1248 CC", max_power="74 bhp", torque="190Nm@ 2000rpm", seats=5)


class Servicio(pbg.CarPriceServiceServicer):
    def Predict(self, request, context):
        return pb.Prediction(predicted_price=1.0, model_version="1")

    def PredictStream(self, request, context):
        for _ in request.items:
            yield pb.Prediction(predicted_price=1.0, model_version="1")


@pytest.fixture
def stub():
    eventos = []

    class AuditorFalso:
        def registrar(self, identidad, accion, resultado, **kw):
            eventos.append((identidad.usuario if identidad else None, accion, str(resultado)))

    srv = grpc.server(futures.ThreadPoolExecutor(max_workers=2), interceptors=[InterceptorJWT(AuditorFalso())])
    pbg.add_CarPriceServiceServicer_to_server(Servicio(), srv)
    puerto = srv.add_insecure_port("127.0.0.1:0")
    srv.start()
    canal = grpc.insecure_channel(f"127.0.0.1:{puerto}")
    yield pbg.CarPriceServiceStub(canal), eventos
    canal.close()
    srv.stop(0)


def md(rol="analista"):
    return [("authorization", f"Bearer {s.emitir_token('jaime', rol)}")]


def codigo(f):
    try:
        f()
        return "OK"
    except grpc.RpcError as e:
        return e.code().name


def test_unary(stub):
    st, eventos = stub
    assert codigo(lambda: st.Predict(pb.Car(**AUTO))) == "UNAUTHENTICATED"
    assert codigo(lambda: st.Predict(pb.Car(**AUTO), metadata=md("invitado"))) == "PERMISSION_DENIED"
    assert codigo(lambda: st.Predict(pb.Car(**AUTO), metadata=md())) == "OK"
    assert [e[2] for e in eventos] == ["UNAUTHENTICATED", "PERMISSION_DENIED", "OK"]


def test_stream(stub):
    st, _ = stub
    lote = pb.CarBatch(items=[pb.Car(**AUTO)] * 3)
    assert codigo(lambda: list(st.PredictStream(lote))) == "UNAUTHENTICATED"
    assert len(list(st.PredictStream(lote, metadata=md()))) == 3
