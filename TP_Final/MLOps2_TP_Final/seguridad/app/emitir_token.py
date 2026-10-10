"""Emite un token JWT para probar las capas (clase 7).

    docker compose --profile manual run --rm emitir-token <usuario> <rol> [--minutos 60]

Roles con permisos: analista, admin (ver PERMISOS en seguridad.py).
"""

import argparse

from app.seguridad import PERMISOS, emitir_token


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("usuario")
    p.add_argument("rol")
    p.add_argument("--minutos", type=int, default=None)
    a = p.parse_args()
    roles = sorted({r for rs in PERMISOS.values() for r in rs})
    if a.rol not in roles:
        print(f"# aviso: el rol '{a.rol}' no tiene permisos (roles: {', '.join(roles)})")
    print(emitir_token(a.usuario, a.rol, a.minutos))


if __name__ == "__main__":
    main()
