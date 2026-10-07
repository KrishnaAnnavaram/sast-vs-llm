import subprocess


def archive(folder, name):
    """Pack a folder into name.tar.gz."""
    command = "tar -czf " + name + ".tar.gz " + folder
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.returncode
