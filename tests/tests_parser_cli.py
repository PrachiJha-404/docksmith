import unittest
import os
import sys

# Ensure we can import cli modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from cli.parser import parse_docksmithfile, ParseError
from cli.parser_cli import parse_cli, BuildCommand, RunCommand, ImagesCommand, RmiCommand

class TestParser(unittest.TestCase):
    def test_parse_docksmithfile_valid(self):
        with open("test_Docksmithfile", "w") as f:
            f.write("# comment line\n")
            f.write("FROM ubuntu:20.04\n")
            f.write("\n") # empty line
            f.write("ENV APP_NAME=myapp\n")
            f.write("COPY . /app\n")
            f.write("WORKDIR /app\n")
            f.write("RUN apt-get update\n")
            f.write('CMD ["python", "app.py"]\n')
            
        instructions = parse_docksmithfile("test_Docksmithfile")
        self.assertEqual(len(instructions), 6)
        
        self.assertEqual(instructions[0].type, "FROM")
        self.assertEqual(instructions[0].args, {"image": "ubuntu:20.04"})
        
        self.assertEqual(instructions[1].type, "ENV")
        self.assertEqual(instructions[1].args, {"key": "APP_NAME", "value": "myapp"})
        
        self.assertEqual(instructions[2].type, "COPY")
        self.assertEqual(instructions[2].args, {"src": ".", "dest": "/app"})
        
        self.assertEqual(instructions[3].type, "WORKDIR")
        self.assertEqual(instructions[3].args, {"path": "/app"})
        
        self.assertEqual(instructions[4].type, "RUN")
        self.assertEqual(instructions[4].args, {"cmd": "apt-get update"})
        
        self.assertEqual(instructions[5].type, "CMD")
        self.assertEqual(instructions[5].args, {"cmd": ["python", "app.py"]})
        
        os.remove("test_Docksmithfile")

    def test_parse_docksmithfile_invalid_cmd(self):
        with open("test_Docksmithfile_inv_cmd", "w") as f:
            f.write("CMD python app.py\n")
            
        with self.assertRaises(ParseError) as context:
            parse_docksmithfile("test_Docksmithfile_inv_cmd")
        self.assertIn("Line 1:", str(context.exception))
        self.assertIn("must be a JSON array", str(context.exception))
        
        os.remove("test_Docksmithfile_inv_cmd")
        
    def test_parse_docksmithfile_unknown_instruction(self):
        with open("test_Docksmithfile_unk", "w") as f:
            f.write("INVALID instruction here\n")
            
        with self.assertRaises(ParseError) as context:
            parse_docksmithfile("test_Docksmithfile_unk")
        self.assertIn("Line 1:", str(context.exception))
        self.assertIn("Unknown instruction INVALID", str(context.exception))
        
        os.remove("test_Docksmithfile_unk")

    def test_missing_arguments(self):
        cases = [
            ("FROM\n", "FROM requires an image"),
            ("WORKDIR\n", "WORKDIR requires a path"),
            ("RUN\n", "RUN requires a command"),
            ("ENV\n", "Invalid ENV format")
        ]
        for content, err_msg in cases:
            with open("test_tmp", "w") as f:
                f.write(content)
            try:
                with self.assertRaises(ParseError) as ctx:
                    parse_docksmithfile("test_tmp")
                self.assertIn(err_msg, str(ctx.exception))
            finally:
                if os.path.exists("test_tmp"):
                    os.remove("test_tmp")

class TestCLI(unittest.TestCase):
    def test_build_command(self):
        cmd = parse_cli(["build", "-t", "myapp:latest", "--no-cache", "./sample_app"])
        self.assertIsInstance(cmd, BuildCommand)
        self.assertEqual(cmd.tag, "myapp:latest")
        self.assertEqual(cmd.context, "./sample_app")
        self.assertEqual(cmd.no_cache, True)

    def test_run_command(self):
        cmd = parse_cli(["run", "-e", "FOO=BAR", "-e", "A=B", "myapp:latest", "sh", "-c", "echo test"])
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.tag, "myapp:latest")
        self.assertEqual(cmd.env_overrides, ["FOO=BAR", "A=B"])
        self.assertEqual(cmd.cmd, ["sh", "-c", "echo test"])

    def test_images_command(self):
        cmd = parse_cli(["images"])
        self.assertIsInstance(cmd, ImagesCommand)

    def test_rmi_command(self):
        cmd = parse_cli(["rmi", "myapp:latest"])
        self.assertIsInstance(cmd, RmiCommand)
        self.assertEqual(cmd.tag, "myapp:latest")

if __name__ == "__main__":
    unittest.main()