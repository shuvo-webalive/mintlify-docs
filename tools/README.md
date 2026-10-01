# API reference generator

Builds `api-reference/openapi.json`, every module's endpoint pages under `api-reference/<module>/`,
each module's overview page (`<module>.mdx` at the docs root), `snippets/client-setup.mdx` and
`snippets/client-build.mdx` (the registration and client line the Authentication page imports), and
the **API reference** part of the `docs.json` navigation.
This folder is listed in `.mintignore`, so it is never published.

```bash
cd tools
python build_reference.py
```

| Path | What it holds |
| --- | --- |
| `modules.json` | The areas and modules to publish, in sidebar order. Add a module here to publish it. |
| `modules/<module>.json` | One module's facts: `tag`, `slug`, `base`, overview text (`intro`, `warning`, `notes`), `endpoints` (paths, parameters, bodies, responses, plain-language wording, `example_call` for the samples) and `schemas`. Written from the SDKs' `ENDPOINTS.md`, docstrings, typed views and live test bodies. |
| `snippets/<sdk>/setup.json` | `register`: the credentials registration an app runs once at startup, shown only on the Authentication page. `client`: the line that gets a client from that registration, shown at the top of every sample. Raise-on-error is set in `register`. |
| `snippets/<sdk>/<module>.json` | One sample per endpoint: the call and any imports it needs. The build puts the `client` line in front and merges the imports. |
| `build_reference.py` | Writes everything listed above. |

The build fails when:

- any SDK is missing a sample for any endpoint of a published module (an endpoint is documented only
  when all seven SDKs have it),
- endpoint keys repeat within a module,
- the spec contains a development host, an API version other than v4, or a dash character.

To compile the registration and every sample exactly as the pages show them, write them out with
`python build_reference.py --programs <folder>` (one folder per SDK, module and endpoint; `--sdk` to
pick one SDK) and build each one against that SDK's `development` branch before publishing.

Two modules may use the same schema name; the later one is prefixed with its module name. Do not edit
generated files by hand; change the inputs here and rebuild.
