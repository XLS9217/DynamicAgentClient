# dynamic-agent-client

WebSocket + HTTP client library for consuming the dynamic agent service.

## Installing the client (in another project)

The client is published as its own git repo:
`https://github.com/XLS9217/DynamicAgentClient.git`

The package name is `dynamic-agent-client`; import it as `dynamic_agent_client`.

pip:

```bash
pip install "git+https://github.com/XLS9217/DynamicAgentClient.git"
```

uv:

```bash
uv add "git+https://github.com/XLS9217/DynamicAgentClient.git"
```

Pin to a tag/branch/commit for reproducibility:

```bash
uv add "git+https://github.com/XLS9217/DynamicAgentClient.git@v0.1.2"
```

Then:

```python
from dynamic_agent_client import ...
```

## Pushing changes to the client repo

The client is developed here in the monorepo under `dynamic_agent_client/`, but
the standalone repo (`client_origin`) has those folder contents at its **root**.
The two are kept in sync with `git subtree` using the prefix `dynamic_agent_client`.

After committing your changes in the monorepo, push the subtree:

```bash
git subtree push --prefix=dynamic_agent_client client_origin main
```

`client_origin` is already configured as a remote:
`https://github.com/XLS9217/DynamicAgentClient.git`

If the remote is missing on a fresh clone, add it first:

```bash
git remote add client_origin https://github.com/XLS9217/DynamicAgentClient.git
```

Remember to bump `version` in `pyproject.toml` when publishing changes that
consumers should pick up, and tag the release if you pin by tag.