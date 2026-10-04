"""Builds the API reference: api-reference/openapi.json, the endpoint pages, each module's overview
page, the client setup snippets and the API reference part of the docs.json navigation.

Modules are listed in modules.json. Each module's endpoint facts live in modules/<module>.json, and its
code samples in snippets/<sdk>/<module>.json, one file per SDK, each compiled against that SDK. An
endpoint is written only when all seven SDKs have a sample for it; the build fails otherwise.
"""

import argparse
import json
import pathlib
import re
import sys
import types
import urllib.parse

TOOLS = pathlib.Path(__file__).resolve().parent
DOCS = TOOLS.parent
OUT = DOCS / "api-reference"
MODULES = TOOLS / "modules"
SNIPPETS = TOOLS / "snippets"
SDKS = [
    ("python", "python", "Python"),
    ("js", "javascript", "JavaScript"),
    ("php", "php", "PHP"),
    ("java", "java", "Java"),
    ("dotnet", "csharp", ".NET"),
    ("dart", "dart", "Dart"),
    ("go", "go", "Go"),
]
FORBIDDEN = re.compile(r"dev-api\.exsited|dev\.exsited|/api/v[123]/|[\u2013\u2014]", re.I)
METHOD_COLOURS = {"GET": "#0f7b6c", "POST": "#2563eb", "PUT": "#b45309", "PATCH": "#7a5af8",
                  "DELETE": "#c2410c", "HEAD": "#475467"}


def load_module(name):
    facts = json.loads((MODULES / (name + ".json")).read_text(encoding="utf-8"))
    return types.SimpleNamespace(
        NAME=name, TAG=facts["tag"], SLUG=facts["slug"], BASE=facts["base"], ICON=facts.get("icon"),
        OVERVIEW_DESCRIPTION=facts["overview_description"], INTRO=facts["intro"],
        WARNING=facts.get("warning"), NOTES=facts.get("notes", []), SCHEMAS=facts.get("schemas", {}),
        ENDPOINTS=facts["endpoints"])


def load_areas(every_module=False):
    if every_module:
        names = sorted(path.stem for path in MODULES.glob("*.json"))
        return [{"name": name, "icon": None, "modules": [load_module(name)]} for name in names]
    listing = json.loads((TOOLS / "modules.json").read_text(encoding="utf-8"))
    return [dict(area, modules=[load_module(name) for name in area["modules"]]) for area in listing["areas"]]


def load_json(path, problems, what):
    if not path.is_file():
        problems.append("no %s (%s)" % (what, path))
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def curl(endpoint):
    call = endpoint.get("example_call", {})
    path = endpoint["path"]
    for name, value in call.get("path", {}).items():
        path = path.replace("{%s}" % name, urllib.parse.quote(str(value), safe=""))
    query = call.get("query", "")
    if isinstance(query, dict):
        query = urllib.parse.urlencode({key: str(value).lower() if isinstance(value, bool) else value
                                        for key, value in query.items()})
    url = "$EXSITED_BASE_URL/api/v4" + path + ("?" + query if query else "")
    method = endpoint["method"]
    lines = ["curl %s\"%s\" \\" % ("-I " if method == "HEAD" else "-X %s " % method, url),
             "  -H \"Authorization: Bearer $ACCESS_TOKEN\""]
    body = call.get("body", (endpoint.get("body") or {}).get("example"))
    if call.get("output"):
        lines[-1] += " \\"
        lines.append("  -o %s" % call["output"])
    elif endpoint.get("multipart"):
        parts = []
        note = call.get("note")
        if isinstance(note, str):
            parts.append("  --form-string %s" % shell_quote("note=" + note))
        elif isinstance(note, dict):
            parts += ["  --form-string %s" % shell_quote("%s=%s" % (key, value)) for key, value in note.items()]
        if call.get("file"):
            parts.append("  -F \"file=@%s\"" % call["file"])
        for part in parts:
            lines[-1] += " \\"
            lines.append(part)
    elif body is not None:
        lines[-1] += " \\"
        lines.append("  -H \"Content-Type: application/json\" \\")
        lines.append("  -d '%s'" % json.dumps(body, indent=2).replace("\n", "\n  "))
    return "\n".join(lines)


def shell_quote(text):
    return "'" + str(text).replace("'", "'\\''") + "'"


def without_path_example(parameter):
    if parameter.get("in") != "path":
        return parameter
    schema = {k: v for k, v in parameter.get("schema", {}).items() if k != "example"}
    return dict({k: v for k, v in parameter.items() if k != "example"}, schema=schema)


IMPORT_LINE = {
    "python": re.compile(r"(import|from) \S"),
    "js": re.compile(r"import \S"),
    "php": re.compile(r"(use|require) \S"),
    "java": re.compile(r"import \S"),
    "dotnet": re.compile(r"using [\w.]+;$"),
    "dart": re.compile(r"import \S"),
}
PROGRAM_FILES = {"python": "main.py", "js": "main.mjs", "php": "main.php", "java": "Main.java",
                 "dotnet": "Program.cs", "dart": "main.dart", "go": "main.go"}


def split_imports(sdk, code):
    """Splits the import lines at the top of a sample or setup from the code below them."""
    if sdk == "go":
        block = re.match(r"\s*import \((.*?)\n\)\n", code, re.S)
        if not block:
            return [], code.strip("\n")
        return [line.strip() for line in block.group(1).splitlines() if line.strip()], code[block.end():].strip("\n")
    lines = code.strip("\n").splitlines()
    imports = []
    while lines and (not lines[0].strip() or IMPORT_LINE[sdk].match(lines[0])):
        line = lines.pop(0)
        if line.strip():
            imports.append(line)
    return imports, "\n".join(lines).strip("\n")


def indent(code, prefix):
    return "\n".join(prefix + line if line.strip() else "" for line in code.splitlines())


def used(name, code):
    return re.search(r"(?<![\w.])%s\b" % re.escape(name), code) is not None


def python_program(imports, code, complete):
    standard = sorted({line for line in imports if "exsited" not in line})
    sdk = sorted({line for line in imports if "exsited" in line})
    return "\n\n".join(part for part in ["\n".join(standard), "\n".join(sdk), code] if part)


def js_program(imports, code, complete):
    names = {}
    for line in imports:
        found = re.match(r"import \{(.*)\} from '(.*)';$", line)
        if not found:
            raise SystemExit("cannot merge the JavaScript import: " + line)
        listed = names.setdefault(found.group(2), [])
        listed += [name.strip() for name in found.group(1).split(",") if name.strip() not in listed]
    order = sorted(names, key=lambda source: (not source.startswith("node:"), source))
    return "\n".join("import {%s} from '%s';" % (", ".join(names[source]), source) for source in order) + "\n\n" + code


def php_program(imports, code, complete):
    requires = "\n".join(line for line in imports if line.startswith("require"))
    uses = "\n".join(sorted({line for line in imports if line.startswith("use ")}))
    return "\n\n".join(part for part in ["<?php" if complete else "", requires, uses, code] if part)


def java_program(imports, code, complete):
    kept = "\n".join(sorted({line for line in imports if used(line.rstrip(";").rsplit(".", 1)[1], code)}))
    if not complete:
        return kept + "\n\n" + code
    return (kept + "\n\npublic class Main {\n    public static void main(String[] args) throws Exception {\n"
            + indent(code, " " * 8) + "\n    }\n}")


def dotnet_program(imports, code, complete):
    return "\n".join(dict.fromkeys(imports)) + "\n\n" + code


def dart_program(imports, code, complete):
    groups = [sorted({line for line in imports if "'dart:" in line}), sorted({line for line in imports if "'dart:" not in line})]
    head = "\n\n".join("\n".join(group) for group in groups if group)
    if not complete:
        return head + "\n\n" + code
    return head + "\n\nFuture<void> main() async {\n" + indent(code, "  ") + "\n}"


def go_program(imports, code, complete):
    def name(spec):
        parts = spec.split()
        return parts[0] if len(parts) == 2 else parts[-1].strip('"').rsplit("/", 1)[-1]
    kept = [spec for spec in dict.fromkeys(imports) if used(name(spec), code)]
    standard = sorted(spec for spec in kept if "." not in spec.split()[-1].split("/")[0])
    other = sorted(spec for spec in kept if spec not in standard)
    block = "\n".join("\t" + spec if spec else "" for spec in standard + ([""] if standard and other else []) + other)
    head = "import (\n" + block + "\n)"
    if not complete:
        return head + "\n\n" + code
    return "package main\n\n" + head + "\n\nfunc main() {\n" + indent(code, "\t") + "\n}"


PROGRAMS = {"python": python_program, "js": js_program, "php": php_program, "java": java_program,
            "dotnet": dotnet_program, "dart": dart_program, "go": go_program}


def program(sdk, parts, complete=False):
    """Joins code parts in order with their imports merged at the top. A complete program also gets
    what its language needs to compile on its own, such as a main function."""
    imports, codes = [], []
    for part in parts:
        part_imports, part_code = split_imports(sdk, part)
        imports += part_imports
        codes.append(part_code)
    return PROGRAMS[sdk](imports, "\n\n".join(code for code in codes if code), complete) + "\n"


def operation(module, endpoint, snippets, setups):
    samples = [{"lang": "bash", "label": "cURL", "source": curl(endpoint)}]
    for sdk, lang, label in SDKS:
        code = program(sdk, [setups[sdk]["client"], snippets[sdk]["endpoints"][endpoint["key"]]["code"]])
        samples.append({"lang": lang, "label": label, "source": code})
    op = {
        "tags": [module.TAG],
        "summary": endpoint["title"],
        "operationId": module.NAME + "_" + endpoint["key"],
        "description": endpoint["description"],
        "parameters": [without_path_example(p) for p in endpoint.get("parameters", [])],
        "responses": {},
        "x-codeSamples": samples,
    }
    if endpoint.get("body"):
        media = "multipart/form-data" if endpoint.get("multipart") else "application/json"
        content = {"schema": endpoint["body"]["schema"]}
        if endpoint["body"].get("example") is not None and not endpoint.get("multipart"):
            content["example"] = endpoint["body"]["example"]
        op["requestBody"] = {"required": True, "content": {media: content}}
    for status, response in endpoint["responses"].items():
        entry = {"description": response["description"]}
        if "schema" in response:
            content = {"schema": response["schema"]}
            if "example" in response:
                content["example"] = response["example"]
            entry["content"] = {response.get("content_type", "application/json"): content}
        elif int(status) >= 400:
            entry["content"] = {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
        op["responses"][status] = entry
    return op


TOKEN_CURL = """curl -X POST "$EXSITED_BASE_URL/api/v4/oauth2/token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "grant_type": "client_credentials",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "YOUR_REDIRECT_URI"
  }'"""


def token_operation():
    return {
        "tags": ["Authentication"],
        "summary": "Get an access token",
        "operationId": "get_access_token",
        "description": "Exchanges your API credentials for an access token. Send the token as `Authorization: Bearer ACCESS_TOKEN` on every other call. The SDKs make this call for you and renew the token before it expires.",
        "security": [],
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": {"type": "object", "required": ["grant_type", "client_id", "client_secret", "redirect_uri"], "properties": {
                "grant_type": {"type": "string", "enum": ["client_credentials", "refresh_token"], "description": "`client_credentials` for a new token, or `refresh_token` to renew one."},
                "client_id": {"type": "string", "description": "Your integration's client ID."},
                "client_secret": {"type": "string", "description": "The secret paired with the client ID."},
                "redirect_uri": {"type": "string", "description": "The redirect URI registered for your integration. Required with `client_credentials`; not sent with `refresh_token`."},
                "refresh_token": {"type": "string", "description": "With `refresh_token` only: the `refresh_token` from an earlier token response."},
            }},
            "example": {"grant_type": "client_credentials", "client_id": "YOUR_CLIENT_ID", "client_secret": "YOUR_CLIENT_SECRET", "redirect_uri": "YOUR_REDIRECT_URI"},
        }}},
        "responses": {
            "200": {"description": "The access token.", "content": {"application/json": {"schema": {"type": "object", "properties": {
                "access_token": {"type": "string", "description": "Send this as `Authorization: Bearer ACCESS_TOKEN`.", "example": "ACCESS_TOKEN"},
                "expires_in": {"type": "integer", "description": "Seconds until the token expires, for example `3600`.", "example": 3600},
                "refresh_token": {"type": "string", "description": "Exchanged for a new access token when this one expires.", "example": "REFRESH_TOKEN"},
            }}}}},
            "302": {"description": "The credentials were not accepted. The API redirects to its sign-in page instead of returning an error body, so this page shows `redirect to unsafe URL blocked`."},
        },
        "x-codeSamples": [{"lang": "bash", "label": "cURL", "source": TOKEN_CURL}],
    }


ERROR_SCHEMA = {
    "type": "object",
    "description": "Every failed call returns this body.",
    "properties": {
        "object": {"type": "string", "description": "Always `error`."},
        "request_id": {"type": "string", "description": "Quote this to support."},
        "status": {"type": "integer", "description": "The HTTP status."},
        "code": {"type": "string", "description": "What went wrong, such as `validation_error`."},
        "message": {"type": "string", "description": "A short description of the problem."},
        "doc_url": {"type": "string", "description": "A link to more about this error."},
        "errors": {"type": "array", "description": "One entry per field that failed.", "items": {"type": "object", "properties": {
            "field": {"type": "string"}, "code": {"type": "string"}, "message": {"type": "string"}, "doc_url": {"type": "string"}}}},
    },
}


TOKEN_PAGE = """---
title: "Get an access token"
description: "Exchange your API credentials for the token every other call needs."
openapi: "POST /oauth2/token"
---

Every call to the API needs an access token. Request one here with your API credentials, then send
it as `Authorization: Bearer ACCESS_TOKEN`. The SDKs make this call for you, so you only need it for
cURL, another HTTP client, or to try the API on this site. A token lasts `expires_in` seconds.

<Steps>
  <Step title="Enter your API host and credentials">
    Click **Try it**, set `host` to your Exsited API host name (without `https://`), choose
    `client_credentials` for `grant_type`, and fill in your client ID, client secret and redirect URI.
  </Step>
  <Step title="Send the request">
    The response holds `access_token`, `refresh_token` and `expires_in`.
  </Step>
  <Step title="Use the token">
    On any other endpoint, click **Try it**, set the same `host`, and paste the token into
    **Authorization**.
  </Step>
</Steps>

<Note>
  If the credentials are wrong, the API returns a redirect to its sign-in page rather than an
  error, and this page shows `redirect to unsafe URL blocked`. Check the client ID, client secret
  and redirect URI, and send again.
</Note>

<Warning>
  A new token for the same credentials ends the previous one, so an app already running with those
  credentials has to get a token again. Calls you make here run against your real data: creating,
  changing and deleting records is real. Requests are sent through Mintlify's servers. Use test data,
  and never share your credentials.
</Warning>
"""

CURL_SETUP = """curl -X POST "$EXSITED_BASE_URL/api/v4/oauth2/token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "grant_type": "client_credentials",
    "client_id": "'"$EXSITED_CLIENT_ID"'",
    "client_secret": "'"$EXSITED_CLIENT_SECRET"'",
    "redirect_uri": "'"$EXSITED_REDIRECT_URI"'"
  }'"""


def prefixed_schemas(areas):
    """Merge every module's schemas; a name already taken by an earlier module gets the module's prefix."""
    merged, renames = {}, {}
    for area in areas:
        for module in area["modules"]:
            mapping = {}
            for name, schema in module.SCHEMAS.items():
                if name in merged and merged[name] != schema:
                    mapping[name] = "".join(part.capitalize() for part in module.NAME.split("_")) + name
            renames[module.NAME] = mapping
            for name, schema in module.SCHEMAS.items():
                merged[mapping.get(name, name)] = json.loads(rename_refs(json.dumps(schema), mapping))
    return merged, renames


def rename_refs(text, mapping):
    for old, new in mapping.items():
        text = text.replace('"#/components/schemas/%s"' % old, '"#/components/schemas/%s"' % new)
    return text


def spec(areas, snippets, setups, schemas, renames):
    paths = {"/oauth2/token": {"post": token_operation()}}
    tags = [{"name": "Authentication"}]
    for area in areas:
        for module in area["modules"]:
            tags.append({"name": module.TAG})
            for endpoint in module.ENDPOINTS:
                op = operation(module, endpoint, snippets[module.NAME], setups)
                op = json.loads(rename_refs(json.dumps(op), renames[module.NAME]))
                paths.setdefault(endpoint["path"], {})[endpoint["method"].lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "Exsited API", "version": "v4"},
        "servers": [{
            "url": "https://{host}/api/v4",
            "variables": {"host": {"default": "your-api-host.example.com", "description": "Your Exsited API host name, without https://."}},
        }],
        "security": [{"bearerAuth": []}],
        "tags": tags,
        "paths": paths,
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "description": "An access token from `POST /api/v4/oauth2/token`. The SDKs get and renew it for you."}},
            "schemas": dict(schemas, Error=ERROR_SCHEMA),
        },
    }


def page(endpoint):
    note = ("The SDK samples get their client from credentials your app registers once when it starts, as shown in "
            "[Authentication](/authentication#set-up-a-client). To try the call here, click **Try it**, set `host` to your Exsited API host name and paste an access token from "
            "[Get an access token](/api-reference/authentication/get-an-access-token).")
    if endpoint.get("body") and not endpoint.get("multipart"):
        note += " To send a raw JSON body instead of filling in fields, copy the cURL sample and edit its `-d` payload."
    return "\n".join([
        "---",
        "title: \"%s\"" % endpoint["title"],
        "description: \"%s\"" % endpoint["summary"].replace("\"", "'"),
        "openapi: \"%s %s\"" % (endpoint["method"], endpoint["path"]),
        "---",
        "",
        endpoint["description"],
        "",
    ] + (["<Warning>", "  " + endpoint["warning"], "</Warning>", ""] if endpoint.get("warning") else []) + [
        "<Note>%s</Note>" % note,
        "",
    ])


def badge(method):
    return ('<span style={{fontFamily: "var(--font-mono, monospace)", fontSize: "0.72rem", fontWeight: 700, '
            'letterSpacing: "0.02em", color: "%s"}}>%s</span>' % (METHOD_COLOURS[method], method))


def code_group(setups, field, curl_tab=None, complete=False):
    tabs = ["<CodeGroup>"]
    if curl_tab:
        tabs += ["```bash cURL", curl_tab, "```", ""]
    for sdk, lang, label in SDKS:
        tabs += ["```%s %s" % (lang, label), program(sdk, [setups[sdk][field]], complete).rstrip(), "```", ""]
    tabs.append("</CodeGroup>")
    return "\n".join(tabs) + "\n"


def overview(module):
    rows = ["| [%s](/api-reference/%s/%s) | %s | `%s` | %s |" % (
        endpoint["title"], module.SLUG, endpoint["slug"], badge(endpoint["method"]),
        endpoint["path"], endpoint["summary"]) for endpoint in module.ENDPOINTS]
    lines = [
        "---",
        "title: \"%s\"" % module.TAG,
        "sidebarTitle: \"Overview\"",
        "description: \"%s\"" % module.OVERVIEW_DESCRIPTION.replace("\"", "'"),
        "---",
        "",
        module.INTRO,
        "",
    ]
    if getattr(module, "WARNING", None):
        lines += ["<Warning>", "  " + module.WARNING, "</Warning>", ""]
    lines += [
        "## At a glance",
        "",
        "| Endpoint | Method | Path | What it does |",
        "| --- | --- | --- | --- |",
    ] + rows + [
        "",
        "## Before you call",
        "",
        "Register your API credentials once when your app starts, as shown in",
        "[Authentication](/authentication). Every SDK sample on these pages then gets its client in one line.",
        "With cURL, send the access token in an `Authorization` header: `Authorization: Bearer $ACCESS_TOKEN`.",
        "",
    ]
    if getattr(module, "NOTES", None):
        lines += ["## Things to know", ""] + ["- " + note for note in module.NOTES] + [""]
    return "\n".join(lines)


def module_pages(module):
    return [module.SLUG] + ["api-reference/%s/%s" % (module.SLUG, endpoint["slug"]) for endpoint in module.ENDPOINTS]


def navigation(areas):
    groups = [{"group": "Authentication", "icon": "key", "expanded": False,
               "pages": ["api-reference/authentication/get-an-access-token"]}]
    for area in areas:
        modules = area["modules"]
        if not modules:
            continue
        if len(modules) == 1 and modules[0].TAG == area["name"]:
            groups.append({"group": area["name"], "icon": area["icon"], "expanded": False, "pages": module_pages(modules[0])})
        else:
            groups.append({"group": area["name"], "icon": area["icon"], "expanded": False, "pages": [
                {"group": module.TAG, "expanded": False, "pages": module_pages(module)} for module in modules]})
    return groups


def write_programs(target, areas, snippets, setups, sdks):
    """Writes the registration and every sample, exactly as the pages show them, as programs that compile on their
    own, one folder each. Samples leave out the registration, so an import it provides cannot hide a missing one."""
    count = 0
    for sdk in sdks:
        folder = target / sdk / "authentication" / "register"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PROGRAM_FILES[sdk]).write_bytes(program(sdk, [setups[sdk]["register"]], complete=True).encode("utf-8"))
        count += 1
    for area in areas:
        for module in area["modules"]:
            for endpoint in module.ENDPOINTS:
                for sdk in sdks:
                    folder = target / sdk / module.NAME / endpoint["key"]
                    folder.mkdir(parents=True, exist_ok=True)
                    sample = snippets[module.NAME][sdk]["endpoints"][endpoint["key"]]["code"]
                    code = program(sdk, [setups[sdk]["client"], sample], complete=True)
                    (folder / PROGRAM_FILES[sdk]).write_bytes(code.encode("utf-8"))
                    count += 1
    print("Wrote %d programs to %s" % (count, target))
    return 0


def main():
    global MODULES, SNIPPETS
    parser = argparse.ArgumentParser()
    parser.add_argument("--programs", help="write every sample as a program under this folder instead of building")
    parser.add_argument("--sdk", action="append", help="with --programs, only this SDK (repeatable)")
    parser.add_argument("--modules-dir", help="read module facts from this folder")
    parser.add_argument("--snippets-dir", help="read samples from this folder")
    parser.add_argument("--every-module", action="store_true", help="with --programs, every module file, not modules.json")
    args = parser.parse_args()
    if args.modules_dir:
        MODULES = pathlib.Path(args.modules_dir)
    if args.snippets_dir:
        SNIPPETS = pathlib.Path(args.snippets_dir)
    sdks = args.sdk or [sdk for sdk, _, _ in SDKS]
    areas = load_areas(args.every_module)
    problems = []
    setups = {sdk: load_json(SNIPPETS / sdk / "setup.json", problems, "%s setup" % sdk) for sdk in sdks}
    snippets = {}
    for area in areas:
        for module in area["modules"]:
            snippets[module.NAME] = {}
            for sdk in sdks:
                data = load_json(SNIPPETS / sdk / (module.NAME + ".json"), problems, "%s samples for %s" % (sdk, module.NAME))
                snippets[module.NAME][sdk] = data
                if data is None:
                    continue
                for endpoint in module.ENDPOINTS:
                    if endpoint["key"] not in data.get("endpoints", {}):
                        problems.append("%s has no sample for %s.%s" % (sdk, module.NAME, endpoint["key"]))
    if problems:
        print("Build failed: an endpoint is documented only when all seven SDKs have a sample.")
        for problem in problems:
            print("  - " + problem)
        return 1

    keys = [module.NAME + "." + endpoint["key"] for area in areas for module in area["modules"] for endpoint in module.ENDPOINTS]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        print("Build failed: endpoint keys are not unique across modules: %s" % ", ".join(duplicates))
        return 1
    if args.programs:
        return write_programs(pathlib.Path(args.programs), areas, snippets, setups, sdks)
    if len(sdks) != len(SDKS):
        print("Build failed: a page build needs all seven SDKs")
        return 1
    schemas, renames = prefixed_schemas(areas)
    document = json.dumps(spec(areas, snippets, setups, schemas, renames), indent=2, ensure_ascii=False)
    found = FORBIDDEN.search(document)
    if found:
        print("Build failed: the spec contains %r" % found.group(0))
        return 1
    OUT.mkdir(exist_ok=True)
    (OUT / "openapi.json").write_text(document + "\n", encoding="utf-8")
    count = 0
    for area in areas:
        for module in area["modules"]:
            (OUT / module.SLUG).mkdir(parents=True, exist_ok=True)
            for endpoint in module.ENDPOINTS:
                (OUT / module.SLUG / (endpoint["slug"] + ".mdx")).write_text(page(endpoint), encoding="utf-8")
                count += 1
            (DOCS / (module.SLUG + ".mdx")).write_text(overview(module), encoding="utf-8")
    (OUT / "authentication").mkdir(exist_ok=True)
    (OUT / "authentication" / "get-an-access-token.mdx").write_text(TOKEN_PAGE, encoding="utf-8")
    (DOCS / "snippets").mkdir(exist_ok=True)
    (DOCS / "snippets" / "client-setup.mdx").write_text(code_group(setups, "register", CURL_SETUP, complete=True), encoding="utf-8")
    (DOCS / "snippets" / "client-build.mdx").write_text(code_group(setups, "client"), encoding="utf-8")

    docs_json = json.loads((DOCS / "docs.json").read_text(encoding="utf-8"))
    for group in docs_json["navigation"]["groups"]:
        if group["group"] == "API reference":
            group["pages"] = navigation(areas)
    (DOCS / "docs.json").write_text(json.dumps(docs_json, indent=2) + "\n", encoding="utf-8")

    modules = sum(len(area["modules"]) for area in areas)
    print("Built %d modules, %d endpoint pages, their overviews and openapi.json" % (modules, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
