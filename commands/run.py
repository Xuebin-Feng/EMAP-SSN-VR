import os
import Command_Engine

def run(viewer, args):
    if not args or args[0].lower() in ['help', '-h', '--help']:
        msg = "Usage: run <script_path.txt>\nDescription: Executes a list of commands in sequence from a text file or a Python script.\nExample:\n  run my_script.txt"
        Command_Engine.print_help(viewer, msg)
        return

    # The command line is whitespace-split before it reaches us, so a Windows
    # path containing spaces arrives as several args. Rejoin them (and drop any
    # surrounding quotes) when that spelling names a real file.
    joined_path = ' '.join(args).strip().strip('"')
    file_path = joined_path if os.path.exists(joined_path) else args[0]

    if not os.path.exists(file_path):
        msg = f"Error: File '{file_path}' does not exist."
        Command_Engine.print_help(viewer, msg)
        return

    # Read/execute the file and extract commands
    try:
        commands_lines = []
        _, ext = os.path.splitext(file_path)
        
        if ext.lower() == '.py':
            import subprocess
            import sys
            
            print(f"[Run] Executing Python script: {file_path}")
            # Execute python script in a subprocess using the current python executable
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            if result.returncode != 0:
                stderr_output = result.stderr.strip() or "(the script wrote nothing to stderr)"
                msg = f"Error: Python script failed (exit code {result.returncode}):\n{stderr_output}"
                Command_Engine.print_help(viewer, msg)
                return
                
            commands_lines = result.stdout.splitlines()
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                commands_lines = f.readlines()

        # Execute the commands in sequence
        executed_count = 0
        for line in commands_lines:
            cmd_line = line.split('//')[0].strip()
            if not cmd_line:
                continue
            
            parts = cmd_line.split()
            if not parts:
                continue
                
            command_name = parts[0].lower()
            # Viewer.process_command strips a 'vr_' prefix before dispatching,
            # so 'vr_run' has to be caught here too or the guard is bypassed
            # and a self-referencing script recurses until RecursionError.
            if command_name.startswith('vr_'):
                command_name = command_name[3:]
            if command_name == 'run':
                print("Warning: Recursive 'run' command in script ignored to prevent infinite loop.")
                continue
            
            print(f"[Run] Executing: {cmd_line}")
            viewer.process_command(cmd_line, record_history=False)
            executed_count += 1
            
        msg = f"Batch execution completed: {executed_count} commands run."
        Command_Engine.print_help(viewer, msg)
        
    except Exception as e:
        msg = f"Error reading/executing command file: {e}"
        Command_Engine.print_help(viewer, msg)
