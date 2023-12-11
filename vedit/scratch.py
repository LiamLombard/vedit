import subprocess
import multiprocessing
import time
import sys
import os


def get_process_tree():
    try:
        # Run the "wmic" command to get information about processes
        wmic_output = subprocess.check_output(
            ["wmic", "process", "get", "ProcessId,ParentProcessId"]
        )

        # Decode the output and split it into lines
        output = wmic_output.decode("utf-8")
        return output.split("\n")[1:]

        # Iterate through the lines and extract process information

    except subprocess.CalledProcessError as e:
        print("Error running 'wmic' command:", e)
        sys.exit(1)


def get_child_processes(pid):
    relations = get_process_tree()

    def search(pid):
        for line in relations:
            if not line.strip():
                continue
            parent_process_id, process_id = map(
                int, map(str.strip, line.strip().split())
            )
            if parent_process_id == pid:
                yield (process_id)
                yield from search(process_id)

    yield from search(pid)


def get_children() -> list[int]:
    children = list(get_child_processes(os.getpid()))


def run_subprocess():
    p = subprocess.run(
        ["python", "-c", "import time;print('start'); time.sleep(90); print('done')"]
    )


if __name__ == "__main__":
    process = multiprocessing.Process(target=run_subprocess)

    try:
        process.start()
        time.sleep(1)
        ans = get_children()
        print(ans)
        time.sleep(100)

    finally:
        # Terminate the process and its subprocess
        process.kill()
        process.join()  # Wait for the process to finish

    print("Main process completed.")
