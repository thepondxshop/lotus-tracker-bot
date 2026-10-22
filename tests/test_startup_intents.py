"""Execute the real intent initialization without starting Discord or a database."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class StartupIntentTests(unittest.TestCase):
    def test_actual_initialization(self):
        path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.Import) and any(a.name == "os" for a in node.names):
                nodes.append(node)
            elif isinstance(node, ast.Assign) and any(
                (isinstance(t, ast.Name) and t.id == "intents") or
                (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                 and t.value.id == "intents") for t in node.targets
            ):
                nodes.append(node)
        code = compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec")
        for flag, expected in [(None, False), ("false", False), ("true", True), ("TRUE", True)]:
            with self.subTest(flag=flag), patch.dict(os.environ, {}, clear=True):
                if flag is not None:
                    os.environ["LOTUS_XP_MESSAGE_CONTENT"] = flag
                namespace = {"discord": SimpleNamespace(Intents=SimpleNamespace(default=SimpleNamespace))}
                exec(code, namespace)
                self.assertTrue(namespace["intents"].members)
                self.assertIs(namespace["intents"].message_content, expected)


if __name__ == "__main__":
    unittest.main()
