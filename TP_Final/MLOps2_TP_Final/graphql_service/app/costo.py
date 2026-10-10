"""Costo de una consulta GraphQL (clase 7): se calcula y se valida ANTES de ejecutarla.

Reglas:
  - cada campo cuesta 1; `predict` cuesta 10 (corre el modelo);
  - en los campos con argumento `limite`, todo lo que está dentro de `items` se
    multiplica por ese límite (el valor por defecto si no viene; el máximo si viene
    en una variable, porque no se conoce al validar).
Así se frenan los alias en masa y las listas grandes, que el límite de profundidad no ve.

`revisar_consulta` se aplica ANTES de que strawberry lea la consulta (en el context_getter):
limita su largo y la cantidad de fragmentos. Sin eso, una cadena de fragmentos repetidos
(F0 usa F1 dos veces, F1 usa F2 dos veces, ...) hace que la validación (incluido el
límite de profundidad de strawberry) tarde un tiempo exponencial: un DoS barato.
"""

from graphql import FieldNode, FragmentSpreadNode, GraphQLError, InlineFragmentNode, IntValueNode, ValidationRule

COSTO_MAX = 200
MAX_LARGO = 10_000        # caracteres de la consulta
MAX_FRAGMENTOS = 30       # apariciones de "..." (fragmentos con nombre o inline)
COSTO_CAMPO = {"predict": 10}
LIMITE_DEFECTO = {"prediccionesStreaming": 20, "auditoria": 50}
LIMITE_MAXIMO = {"prediccionesStreaming": 500, "auditoria": 500}


def revisar_consulta(texto) -> str | None:
    """Motivo del rechazo si la consulta es demasiado grande para analizarla; None si está bien."""
    if not isinstance(texto, str):
        return None
    if len(texto) > MAX_LARGO:
        return f"consulta demasiado larga: más de {MAX_LARGO} caracteres"
    if texto.count("...") > MAX_FRAGMENTOS:
        return f"consulta con demasiados fragmentos: más de {MAX_FRAGMENTOS}"
    return None


def costo_documento(document) -> int:
    fragmentos = {d.name.value: d for d in document.definitions if d.kind == "fragment_definition"}
    memo = {}   # (fragmento, multiplicador) -> costo: cada fragmento se calcula una sola vez

    def seleccion(sel_set, mult_items, visitados):
        total = 0
        for sel in (sel_set.selections if sel_set else []):
            if isinstance(sel, FieldNode):
                nombre = sel.name.value
                propio = COSTO_CAMPO.get(nombre, 1)
                hijo_mult = mult_items
                if nombre in LIMITE_DEFECTO:
                    arg = next((a.value for a in sel.arguments or [] if a.name.value == "limite"), None)
                    if arg is None:
                        hijo_mult = LIMITE_DEFECTO[nombre]
                    elif isinstance(arg, IntValueNode):
                        hijo_mult = min(max(int(arg.value), 0), LIMITE_MAXIMO[nombre])
                    else:
                        hijo_mult = LIMITE_MAXIMO[nombre]
                if nombre == "items":
                    total += propio + mult_items * seleccion(sel.selection_set, 1, visitados)
                else:
                    total += propio + seleccion(sel.selection_set, hijo_mult, visitados)
            elif isinstance(sel, InlineFragmentNode):
                total += seleccion(sel.selection_set, mult_items, visitados)
            elif isinstance(sel, FragmentSpreadNode) and sel.name.value not in visitados \
                    and sel.name.value in fragmentos:
                clave = (sel.name.value, mult_items)
                if clave not in memo:
                    memo[clave] = seleccion(fragmentos[sel.name.value].selection_set, mult_items,
                                            visitados | {sel.name.value})
                total += memo[clave]
        return total

    return sum(seleccion(d.selection_set, 1, frozenset()) for d in document.definitions
               if d.kind == "operation_definition")


class LimiteCosto(ValidationRule):
    def enter_document(self, node, *_):
        costo = costo_documento(node)
        if costo > COSTO_MAX:
            self.report_error(GraphQLError(f"consulta demasiado costosa: {costo} > {COSTO_MAX}"))
