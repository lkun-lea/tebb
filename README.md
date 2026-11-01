<div align="center">

# tebb.

### Think together. Build together.

A local-first workspace for AI companions, projects, and visual workflows.

[English](README.md) · [简体中文](README.zh-CN.md)

[![Release](https://img.shields.io/github/v/release/lkun-lea/tebb?style=flat-square)](https://github.com/lkun-lea/tebb/releases)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=flat-square)](https://github.com/lkun-lea/tebb/releases)
[![Status](https://img.shields.io/badge/status-early%20preview-8D9B82?style=flat-square)](#project-status)

[Download](https://github.com/lkun-lea/tebb/releases) · [Quick start](#quick-start) · [Documentation](docs/GETTING_STARTED.md) · [Issues](https://github.com/lkun-lea/tebb/issues)

</div>

> Latest published package: [v0.4.1 for Windows x64](https://github.com/lkun-lea/tebb/releases/tag/v0.4.1). This README describes main, which includes changes made after that frozen release.

![tebb v0.4.1 release concept](desk_companion/ui/release-v0.4.1.png)

*Release concept illustration; the actual client is the reference for interface and behavior.*

Bring your own model and work with AI companions alongside your files and projects. Start a private conversation or a group, research a question, edit code, inspect the results, and keep useful material for the next task.

## What you can do

### Work with a team of companions

tebb helps turn goals into tasks. Research, writing, coding, and chart companions have their own personality, model, tools, and avatar. Create your own companions, mention participants with `@`, select a skill with `/`, and attach relevant files. Conversations and the companion directory remain separate, so earlier work is easy to continue.

> “Research this project's technical approach, verify primary sources, and write a report.”

### Open a folder and build in it

Browse files, preview Markdown, and inspect code beside the conversation. Grant editing and command permissions per project. Companions can make changes, run checks, and report actual diffs, output and exit codes. Reading example code does not require execution permissions.

Each project keeps its own directories, permissions, instructions, and conversations. Public GitHub Node/Python web projects can use an explicitly enabled Docker Sandboxes environment for dependencies, execution, logs, a local preview and stopping the service. See [folder projects](docs/FOLDER_PROJECTS.md), [terminal](docs/TERMINAL.md), and [project runtime](docs/PROJECT_RUNTIME.md).

### Keep evidence and notes useful

Read documents, web pages and local files alongside chat. Select the material to include in a task. Notebooks combine sources, questions and saved notes; knowledge search preserves citations and links back to the original material. A saved answer can become evidence for the next conversation. See [workspace layout](docs/WORKSPACE_UI.md).

<details>
<summary>Notebook and citation preview</summary>

![Notebook, selected sources and citations](docs/images/notebook.png)

*Existing notebook components with anonymous demonstration material.*

</details>

### Compose visual workflows

Start with editable examples for technology news, video notes, or Feishu publishing. Drag atomic capabilities onto the design page, connect them, inspect inputs and outputs step by step, then run or schedule a saved version. Ask a companion to create reusable declarative capabilities and save a workflow draft using the same services. Saving a draft does not execute it or enable publication.

Video reading uses actual available subtitles and reports coverage gaps. Feishu document creation, table records and group messages are separate optional nodes with fixed targets and explicit publication confirmation. Connections and video login live in settings. These integrations are optional capabilities rather than prerequisites for the agent. See [workflows](docs/WORKFLOWS.md).

### Organize work and keep a desktop entry point

Move local work items through todo, in progress, review and done. Assign a project or AI owner, then explicitly hand a task to a companion. The calendar supports local appointments, month/week/day views, rescheduling and optional Feishu synchronization. See [work board](docs/WORK_BOARD.md) and [calendar](docs/CALENDAR.md).

A small, customizable desktop pet opens floating chat. Hide it or change its appearance from the pet page; closing a floating window does not stop tasks.

## Stay in control

| Concern | Behavior |
| --- | --- |
| Model choice | Bring your own API key for a compatible Chat Completions service; configure models per companion. |
| Task progress | Streaming output, task timelines, tool receipts, clarification and cancellation. |
| File access | Explicit project directories with separate read, edit and command permissions. |
| Verification | Actual changes and command results, with generated output distinguished from verified execution. |
| Extensions | [Versioned official skills](https://github.com/lkun-lea/tebb-skills), configured tools and supported MCP connections. Skills do not grant permissions. |
| Memory and debugging | Inspect actual model input, source versions, selected/excluded memory, next-send previews and isolated trials. See [memory](docs/MEMORY_REDESIGN.md). |

## Quick start

1. Download the Windows x64 ZIP from [Releases](https://github.com/lkun-lea/tebb/releases) and extract it completely.
2. Run `tebb.exe`, keeping its `runtime` directory alongside it.
3. Follow onboarding to enter the model API URL, model ID and API key, then save and test the connection.
4. To work on local code, open a folder from companion chat and configure its permissions.

Windows 10/11 x64 and WebView2 Runtime are required. The portable package includes Python; installing Python, Node or Rust is unnecessary for the packaged client. Model service charges may apply, and tool execution requires model support for tool calling.

Optional connections can be configured later. See [getting started](docs/GETTING_STARTED.md). To run from source, follow [development](docs/DEVELOPMENT.md): Atlas and tebb-skills use pinned commits, and skills must be explicitly prepared before first use. The app does not download skill updates at startup.

## Project status

tebb is an early preview, currently focused on a personal Windows installation. Conversations and configuration are stored locally. Required task context is sent to your selected model or configured tool service.

- Scheduled workflows require the local app to be running; they do not continue in the cloud after shutdown.
- Subtitle availability and coverage limit video summaries; missing content is reported.
- Commands require configured permissions and a ready isolation backend. The offline terminal and Docker project runtime have different capabilities.
- Model and network requests can time out. Completed external actions are not automatically undone or repeated; unknown write results require reconciliation.
- Cloud hosting, remote access and multi-user administration are not current product guarantees. UI localization beyond these READMEs is outside this change.

See [issues](https://github.com/lkun-lea/tebb/issues) and [performance evidence](docs/PERFORMANCE.md) for current limits and measurements.

## Documentation and contributing

| Topic | Documentation |
| --- | --- |
| Setup, model connections and workspace | [Getting started](docs/GETTING_STARTED.md) · [Companions](docs/LOCAL_COLLABORATION.md) |
| Visual automation | [Workflows](docs/WORKFLOWS.md) · [Official skills](https://github.com/lkun-lea/tebb-skills) |
| Feishu connections and video sources | [Feishu](docs/FEISHU_AGENT.md) · [Video](docs/VIDEO_SUMMARIES.md) |
| Execution, permissions and debugging | [Terminal](docs/TERMINAL.md) · [Agent debugging](docs/AGENT_DEBUG.md) |
| Development and releases | [Development](docs/DEVELOPMENT.md) · [Contributing](CONTRIBUTING.md) · [Releasing](docs/RELEASING.md) |

Bug reports, reproducible examples, documentation and code improvements are welcome. Remove credentials and private conversation content before sharing diagnostics.

tebb was previously named ZhiXing. GitHub redirects the old repository links; existing user data is retained. See [branding](docs/BRAND.md).

## License and acknowledgements

tebb's own code is [MIT licensed](LICENSE). Atlas is also MIT licensed; third-party dependencies, fonts and assets retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md). MIT does not grant rights to brands, character designs, model weights or separately licensed assets. Personal Live2D/Core assets and model weights are not included in public release packages.

Thanks to Atlas, Tauri, React, React Flow, xterm.js, bubblewrap, yt-dlp and the other projects used here.
