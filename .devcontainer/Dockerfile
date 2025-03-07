{
    "name": "Flood Test Environment",
    "dockerFile": "Dockerfile",
    "settings": {
        "terminal.integrated.shell.linux": "/bin/bash"
    },
    "extensions": [
        "ms-python.python",
        "ms-azuretools.vscode-docker"
    ],
    "postCreateCommand": "pip install -r requirements.txt && python keep_alive.py",
    "runArgs": ["--cap-add=NET_ADMIN"]
}
