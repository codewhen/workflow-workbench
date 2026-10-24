import ast
import copy
import json
import unittest
from pathlib import Path

from release_workbench.application.compiler import CompilationError
from release_workbench.application.executors import EXECUTORS, calculate
from release_workbench.application.starters import TEMPLATES, card, edge, ref, starter
from release_workbench.domain.cards import REGISTRY, CardSpec
from release_workbench.domain.models import Card, CardResult, Outcome
from release_workbench.domain.values import VOID, ContractError, TypedValue
from release_workbench.infrastructure.documents import SCHEMA, compile_document, parse_document
from tests.support import by_id, sequence


class Contracts(unittest.TestCase):
    def test_registry_schema_executor_contract(self):
        kinds = SCHEMA["$defs"]["card"]["properties"]["kind"]["enum"]
        self.assertEqual(set(kinds), set(REGISTRY))
        self.assertEqual(set(kinds), set(EXECUTORS))
        for kind, spec in REGISTRY.items():
            with self.subTest(kind=kind):
                self.assertIsInstance(spec, CardSpec)
                self.assertEqual(spec.metadata()["kind"], kind)
                self.assertIsInstance(
                    spec.flow_outputs(Card("x", kind, kind, copy.deepcopy(spec.defaults))), tuple
                )
                json.dumps(spec.metadata())

    def test_typed_values(self):
        for value, kind in [
            (False, "boolean"),
            (0, "number"),
            (None, "null"),
            ([], "array"),
            ({}, "object"),
            ("s", "string"),
        ]:
            with self.subTest(kind=kind):
                self.assertEqual(TypedValue.checked(value, kind).type.value, kind)
        self.assertNotEqual(VOID, TypedValue.checked(None))
        self.assertNotIn("value", VOID.to_dict())
        for value, kind in [
            (0, "boolean"),
            (True, "number"),
            ([], "object"),
            (float("nan"), "number"),
            ({1: "a"}, "json"),
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    TypedValue.checked(value, kind)
        result = CardResult("passed", Outcome(TypedValue.checked(False)), ("log",)).to_dict()
        self.assertEqual(result["outcome"]["value"]["value"], False)

    def test_starters_compile(self):
        for name in TEMPLATES:
            with self.subTest(name=name):
                compile_document(starter(name, name))

    def test_old_schema_rejected(self):
        for version in (1, 2):
            with self.assertRaisesRegex(CompilationError, "Unsupported workflow version"):
                compile_document({"version": version})

    def test_domain_has_no_effect_adapters(self):
        base = Path(__file__).parents[1] / "src/release_workbench"
        for layer in ("domain", "application"):
            for file in (base / layer).rglob("*.py"):
                for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn(
                                "release_workbench.infrastructure", alias.name, str(file)
                            )
                            self.assertNotIn("release_workbench.interfaces", alias.name, str(file))
                            if layer == "domain":
                                self.assertNotIn(
                                    "release_workbench.application", alias.name, str(file)
                                )
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotIn("infrastructure", node.module or "", str(file))
                        self.assertNotIn("interfaces", node.module or "", str(file))
                        if layer == "domain":
                            self.assertNotIn("application", node.module or "", str(file))
                        if layer == "domain" and node.level == 0:
                            self.assertNotIn(
                                (node.module or "").split(".")[0],
                                ("os", "pathlib", "subprocess", "asyncio", "http"),
                            )

    def test_bad_defaults_and_fields(self):
        invalid = [
            card("bad", "wait", {"seconds": -1}),
            card("bad", "loop", {"count": -1}),
            card("bad", "python", {"returns": "wat"}),
            card("bad", "bash", {"capture": "xml"}),
            card("bad", "program", {"argv": [1]}),
        ]
        for operation in invalid:
            with self.subTest(kind=operation["kind"]):
                with self.assertRaises(CompilationError):
                    compile_document(sequence(operation))
        raw = starter("Bad")
        raw["inputs"] = {"x": {"type": "boolean", "default": 0}}
        with self.assertRaises(CompilationError):
            compile_document(raw)

    def test_strict_boolean_calculation(self):
        self.assertIs(calculate("equals", False, 0), False)
        self.assertIs(calculate("not", False, None), True)
        with self.assertRaises(ContractError):
            calculate("and", 1, True)

    def test_cycles_and_unreachable_rejected(self):
        raw = sequence(card("work", "wait", {"seconds": 0}))
        raw["graphs"]["main"]["edges"][-1] = edge("work", "work")
        with self.assertRaisesRegex(CompilationError, "cycle"):
            compile_document(raw)
        raw = starter("Bad")
        raw["graphs"]["main"]["cards"].append(card("orphan", "finish"))
        with self.assertRaisesRegex(CompilationError, "unreachable"):
            compile_document(raw)

    def test_functions_require_boolean_and_returns(self):
        raw = starter("Bad", "manual")
        raw["functions"]["approved"]["returns"] = "number"
        with self.assertRaisesRegex(CompilationError, "Boolean"):
            compile_document(raw)
        raw = starter("Bad", "manual")
        by_id(raw, "return", "approval")["config"] = {"value": "yes"}
        with self.assertRaises(CompilationError):
            compile_document(raw)

    def test_recursive_functions_rejected(self):
        raw = starter("Bad", "manual")
        g = raw["graphs"]["approval"]
        g["cards"].insert(1, card("again", "call", {"function": "approved"}))
        g["edges"][0] = edge("start", "again")
        g["edges"].append(edge("again", "ask"))
        with self.assertRaisesRegex(CompilationError, "Recursive"):
            compile_document(raw)

    def test_function_cannot_break_caller_loop(self):
        raw = starter("Bad", "while")
        by_id(raw, "return", "condition")["kind"] = "break"
        with self.assertRaisesRegex(CompilationError, "cannot target a caller"):
            compile_document(raw)

    def test_branch_values_must_be_joined(self):
        raw = starter("Bad", "parallel")
        by_id(raw, "finish")["config"] = {"returns": "json", "value": ref("first")}
        with self.assertRaisesRegex(CompilationError, "not guaranteed"):
            compile_document(raw)

    def test_value_connection_type_mismatch(self):
        raw = sequence(
            card("n", "python", {"code": "return 1", "returns": "number"}),
            card("use", "call", {"function": "boolean-fn"}),
        )
        raw["functions"] = {
            "boolean-fn": {
                "graph": "fn",
                "returns": "boolean",
                "inputs": {"a": {"type": "boolean"}},
            }
        }
        raw["graphs"]["fn"] = {
            "cards": [card("start", "start"), card("return", "return", {"value": True})],
            "edges": [edge("start", "return")],
        }
        raw["graphs"]["main"]["edges"].append(
            {
                "id": "value",
                "kind": "value",
                "source": "n",
                "target": "use",
                "source_port": "value",
                "target_port": "input:a",
            }
        )
        with self.assertRaisesRegex(CompilationError, "incompatible"):
            compile_document(raw)

    def test_yaml_alias_and_tags_rejected(self):
        for text in ("a: &x [1]\nb: *x", "a: !something x"):
            with self.assertRaises(ValueError):
                parse_document(text)

    def test_finish_output_contract_is_checked_before_running(self):
        raw = starter("Output")
        by_id(raw, "finish")["config"] = {"returns": "boolean", "value": None}
        with self.assertRaisesRegex(CompilationError, "Expected boolean"):
            compile_document(raw)

    def test_all_diagnostics_use_card_names_and_graph_locations(self):
        raw = starter("Named diagnostics")
        by_id(raw, "finish")["name"] = "Publish result"
        by_id(raw, "finish")["config"] = {"returns": "boolean", "value": None}
        from copy import deepcopy

        raw["graphs"]["condition"] = deepcopy(raw["graphs"]["main"])
        by_id(raw, "finish", "condition")["name"] = "Condition result"
        by_id(raw, "finish", "condition")["config"] = {"returns": "number", "value": None}
        raw["functions"] = {
            "Check health": {"graph": "condition", "returns": "boolean", "inputs": {}}
        }
        with self.assertRaises(CompilationError) as caught:
            compile_document(raw)
        error = caught.exception
        self.assertEqual(len(error.errors), 3)
        self.assertEqual(len(error.issues), 3)
        self.assertIn("Main workflow › Publish result", error.errors[0])
        self.assertTrue(
            all("Function “Check health” › Condition result" in item for item in error.errors[1:])
        )
        self.assertTrue(all(issue["card"] == "finish" for issue in error.issues))
        self.assertIn("Replace it with a Return card", error.errors[1])
        self.assertNotIn("finish:", str(error))

    def test_finish_can_receive_a_typed_value_connection(self):
        raw = sequence(card("result", "python", {"code": "return True", "returns": "boolean"}))
        by_id(raw, "finish")["config"] = {"returns": "boolean", "value": None}
        raw["graphs"]["main"]["edges"].append(
            {
                "id": "result-value",
                "kind": "value",
                "source": "result",
                "source_port": "value",
                "target": "finish",
                "target_port": "config:value",
            }
        )
        compile_document(raw)

    def test_cards_have_distinct_inherited_implementation_modules(self):
        from release_workbench.application.ports import CardExecutor
        from release_workbench.infrastructure.operations import HANDLERS, OperationHandler

        self.assertEqual(len(REGISTRY), len({type(item).__module__ for item in REGISTRY.values()}))
        self.assertEqual(
            len(EXECUTORS), len({type(item).__module__ for item in EXECUTORS.values()})
        )
        for kind, executor in EXECUTORS.items():
            self.assertIsInstance(executor, CardExecutor)
            self.assertEqual(executor.kind, kind)
        self.assertEqual(len(HANDLERS), len({type(item).__module__ for item in HANDLERS.values()}))
        for kind, handler in HANDLERS.items():
            self.assertIsInstance(handler, OperationHandler)
            self.assertEqual(handler.kind, kind)
            self.assertTrue(REGISTRY[kind].supports_retry)

    def test_structural_cards_cannot_silently_ignore_resource_settings(self):
        raw = starter("Resources", "while")
        by_id(raw, "compare", "condition")["kind"] = "poll"
        by_id(raw, "compare", "condition")["config"] = {"function": "below-limit"}
        by_id(raw, "compare", "condition")["settings"] = {"resources": ["desktop"]}
        with self.assertRaisesRegex(CompilationError, "locks on operations"):
            compile_document(raw)

    def test_compilation_does_not_share_mutable_card_defaults(self):
        raw = starter("Isolated defaults", "parallel")
        workflow = compile_document(raw)
        compiled = next(c for c in workflow.graphs["main"].cards.values() if c.kind == "parallel")
        compiled.config["branches"].append("mutated")
        self.assertNotIn("mutated", REGISTRY["parallel"].defaults["branches"])
        original = next(c for c in raw["graphs"]["main"]["cards"] if c["id"] == compiled.id)
        self.assertNotIn("mutated", original["config"].get("branches", []))

    def test_loop_and_poll_limits_are_finite_and_iterations_integral(self):
        for template, kind, key, value in (
            ("while", "loop", "limit", 2.5),
            ("while", "loop", "timeout", float("nan")),
            ("poll", "poll", "timeout", False),
            ("poll", "poll", "timeout", -1),
        ):
            with self.subTest(kind=kind, key=key, value=value):
                raw = starter("Bounds", template)
                target = next(c for c in raw["graphs"]["main"]["cards"] if c["kind"] == kind)
                target["config"][key] = value
                with self.assertRaisesRegex(CompilationError, "positive"):
                    compile_document(raw)

    def test_polymorphic_result_types_match_dynamic_card_contracts(self):
        from release_workbench.domain.cards import get_spec

        workflow = compile_document(starter("Types", "while"))
        self.assertEqual(
            get_spec("manual").result_type(Card("m", "manual", "Approval", {"mode": "approval"})),
            "void",
        )
        self.assertEqual(
            get_spec("manual").result_type(Card("m", "manual", "Decision", {})), "boolean"
        )
        self.assertEqual(
            get_spec("python").result_type(Card("p", "python", "Python", {"returns": "number"})),
            "number",
        )
        self.assertEqual(
            get_spec("variable").result_type(
                Card("v", "variable", "Count", {"name": "count"}), workflow
            ),
            "number",
        )
        self.assertEqual(
            get_spec("call").result_type(
                Card("c", "call", "Call", {"function": "below-limit"}), workflow
            ),
            "boolean",
        )

    def test_only_visible_fields_are_validated_for_the_selected_mode(self):
        raw = starter("Hidden fields", "while")
        by_id(raw, "repeat")["config"]["count"] = None
        compile_document(raw)

    def test_argument_array_contract_is_owned_by_the_field_descriptor(self):
        from release_workbench.domain.cards import get_spec

        for kind, key in (("program", "argv"), ("script", "arguments")):
            spec = get_spec(kind)
            descriptor = next(field for field in spec.fields if field["key"] == key)
            self.assertEqual(descriptor["items"], "string")
            config = {**spec.defaults, key: [1]}
            self.assertTrue(
                any(
                    "array of strings" in error
                    for error in spec.validate(Card("bad", kind, "Bad", config))
                )
            )

    def test_json_equality_uses_typed_boolean_and_number_semantics_recursively(self):
        self.assertIs(calculate("equals", 1, 1.0), True)
        self.assertIs(calculate("equals", [False], [0]), False)
        self.assertIs(calculate("equals", {"enabled": True}, {"enabled": 1}), False)
        self.assertIs(calculate("equals", {"count": [1]}, {"count": [1.0]}), True)
        self.assertIs(calculate("not_equals", [False], [0]), True)
