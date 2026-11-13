# Security policy

## Reporting a vulnerability

Please report security issues privately by email to **hello@probnode.com** with "security" in
the subject, not in a public issue or pull request. Include what you found, how to reproduce it,
and the versions of `probnode-sdk` / `probnode-mcp` involved.

We will acknowledge your report and keep you informed until the issue is resolved. Please give us a
reasonable time to fix an issue before disclosing it publicly.

This covers the code in this repository and the ProbNode API it talks to (https://probnode.com).

## Supported versions

Security fixes are made in the latest release of each package. Upgrade with:

```sh
pip install -U probnode-sdk probnode-mcp
```

## API keys

Never paste an API key into an issue, a pull request or a log you share. If a key was exposed,
revoke it in your account at https://probnode.com (or with `DELETE /v1/keys/{prefix}`) and create
a new one.
