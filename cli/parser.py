import os

class ParseError(Exception):
    pass

class Instruction:
    def __init__(self, type_: str, raw: str, args: dict):
        self.type = type_
        self.raw = raw
        self.args = args

    def __repr__(self):
        return f"Instruction(type='{self.type}', raw='{self.raw}', args={self.args})"

def parse_docksmithfile(path: str) -> list[Instruction]:
    import json
    instructions = []
    
    with open(path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            raw_line = line.strip()
            
            # Skip empty lines and comments
            if not raw_line or raw_line.startswith('#'):
                continue
                
            parts = raw_line.split(maxsplit=1)
            inst_type = parts[0].upper()
            
            # Fail fast on unknown instruction
            if inst_type not in ("FROM", "COPY", "RUN", "WORKDIR", "ENV", "CMD"):
                raise ParseError(f"Line {line_num}: Unknown instruction {inst_type}")
                
            arg_str = parts[1].strip() if len(parts) > 1 else ""
            args = {}
            
            if inst_type == "FROM":
                if not arg_str:
                    raise ParseError(f"Line {line_num}: FROM requires an image")
                args = {"image": arg_str}
            elif inst_type == "COPY":
                # Expecting format: COPY <src> <dest>
                if not arg_str:
                    raise ParseError(f"Line {line_num}: COPY requires <src> and <dest>")
                try:
                    src, dest = arg_str.rsplit(maxsplit=1)
                    args = {"src": src, "dest": dest}
                except ValueError:
                    raise ParseError(f"Line {line_num}: COPY requires <src> and <dest>")
            elif inst_type == "RUN":
                if not arg_str:
                    raise ParseError(f"Line {line_num}: RUN requires a command")
                args = {"cmd": arg_str}
            elif inst_type == "WORKDIR":
                if not arg_str:
                    raise ParseError(f"Line {line_num}: WORKDIR requires a path")
                args = {"path": arg_str}
            elif inst_type == "ENV":
                # Expecting format: ENV KEY=value
                if "=" in arg_str:
                    k, v = arg_str.split("=", 1)
                    args = {"key": k.strip(), "value": v.strip()}
                else:
                    raise ParseError(f"Line {line_num}: Invalid ENV format, expected KEY=value")
            elif inst_type == "CMD":
                try:
                    cmd_arr = json.loads(arg_str)
                    if not isinstance(cmd_arr, list):
                        raise ValueError()
                    args = {"cmd": cmd_arr}
                except (ValueError, json.JSONDecodeError):
                    raise ParseError(f"Line {line_num}: CMD must be a JSON array")
            
            # Only keep the original line stripped of trailing newlines
            instructions.append(Instruction(type_=inst_type, raw=line.rstrip('\n'), args=args))
            
    return instructions