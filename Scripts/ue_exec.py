"""
Run an arbitrary Python script inside the running Unreal Editor.

Reuses the engine's own Remote Execution client
(Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python/remote_execution.py)
exactly the way Plugins/ComboMCP/engine/bridge.py does, so no C++ plugin or
extra dependency is needed.

NOTE: the command channel is single-client. While this script holds it, the
ComboMCP tools (`combo_*`) cannot connect. It releases the channel on exit.

Usage:
    python ue_exec.py my_script.py
    python ue_exec.py -c "import unreal; print(unreal.SystemLibrary.get_engine_version())"
"""

import argparse
import importlib.util
import os
import sys
import time

ENGINE_CANDIDATES = [
    r"E:\UE_5.7",
    r"D:\UE_5.7",
    r"C:\Program Files\Epic Games\UE_5.7",
]
REMOTE_EXEC_REL = os.path.join(
    "Engine", "Plugins", "Experimental", "PythonScriptPlugin",
    "Content", "Python", "remote_execution.py",
)


def find_engine():
    env = os.environ.get("COMBO_UE_ENGINE")
    for candidate in ([env] if env else []) + ENGINE_CANDIDATES:
        if candidate and os.path.isfile(os.path.join(candidate, REMOTE_EXEC_REL)):
            return candidate
    raise RuntimeError("no Unreal Engine found with remote_execution.py")


def load_remote_execution(engine_root):
    path = os.path.join(engine_root, REMOTE_EXEC_REL)
    spec = importlib.util.spec_from_file_location("combo_remote_execution", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["combo_remote_execution"] = module
    spec.loader.exec_module(module)
    return module


def as_text(value):
    """UE 5.7 hands back log lines as a list of dicts, not a string."""
    if isinstance(value, dict):
        for key in ("output", "text", "line", "message"):
            if key in value:
                return as_text(value[key])
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            text = as_text(item)
            if text and not text.endswith(("\n", "\r")):
                text += "\n"
            parts.append(text)
        return "".join(parts)
    return "" if value is None else str(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?")
    ap.add_argument("-c", "--command")
    ap.add_argument("--project", default="Animation_Sample",
                    help="prefer the editor instance whose project matches")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    if args.command:
        code = args.command
    elif args.script:
        with open(args.script, "r", encoding="utf-8") as fh:
            code = fh.read()
    else:
        ap.error("give a script path or -c COMMAND")

    mod = load_remote_execution(find_engine())
    session = mod.RemoteExecution(mod.RemoteExecutionConfig())
    session.start()
    try:
        deadline = time.time() + 10.0
        nodes = []
        while time.time() < deadline and not nodes:
            nodes = session.remote_nodes
            if not nodes:
                time.sleep(0.25)
        if not nodes:
            print("ERROR: no Unreal Editor found on the remote-execution channel",
                  file=sys.stderr)
            return 2

        chosen = nodes[0]
        for node in nodes:
            if args.project.lower() in str(node.get("project_name", "")).lower():
                chosen = node
                break
        print("# node: %s (%s)" % (chosen.get("project_name"),
                                   chosen.get("engine_version")), file=sys.stderr)

        session.open_command_connection(chosen.get("node_id"))
        raw = session.run_command(code, unattended=True, exec_mode=mod.MODE_EXEC_FILE)
    finally:
        try:
            session.stop()
        except Exception:
            pass

    output = as_text(raw.get("output"))
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    result = as_text(raw.get("result"))
    if result.strip():
        print(result)
    print("[success=%s]" % raw.get("success"), file=sys.stderr)
    return 0 if raw.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
