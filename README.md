# 👋 Hey: ChatGPT client for command line

[![CI](https://github.com/altescy/hey/actions/workflows/ci.yml/badge.svg)](https://github.com/altescy/hey/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/altescy/hey)](https://github.com/altescy/hey/releases)
[![License](https://img.shields.io/github/license/altescy/hey)](https://github.com/altescy/hey/blob/main/LICENSE)

`hey` is a command-line application that provides access to ChatGPT for users who prefer working within a terminal environment.
It is designed to be a non-interactive interface, meaning it processes commands one at a time rather than through continuous conversation.
This approach is tailored for those who require quick and specific interactions with an AI model, without the inconvenience of being tied to a dialog-based interface.

![screenshot](./assets/screenshot.png)

## Features

Key aspects of `hey` include:

- **Command Line Accessibility**: Integrates ChatGPT into the command line, allowing for easy access within a terminal.
- **Non-Interactive Design**: Operates on a single-command basis, focusing on straightforward interactions with ChatGPT.
- **Markdown Readability**: Supports Markdown with syntax highlighting, making outputs easier to read and understand in the terminal.
- **Context Management**: Maintains a conversation context across individual commands, providing relevant and connected responses.
- **Multiple Profiles**: Enables the use of different models and APIs, offering versatility for various user needs.

`hey` aims to provide a practical and efficient way to interact with ChatGPT for users who are accustomed to the command-line environment.

## Installation

```shell
pipx install git+https://github.com/altescy/hey@latest
```

## Quick Start

Set your `OPENAI_API_KEY` to access ChatGPT API:

```shell
export OPENAI_API_KEY=...
```

Start a new conversation (context) with `hey --new` like below.
`[title]` is an optional argument to name the conversation:

```shell
hey --new=[title] [You can write a message here!]
```

Once you create a context, `hey` operates within that context, allowing you to continue the conversation seamlessly across different command executions:

```shell
hey [Write your response here!]
```

You can pass contents from stdin as well:

```shell
cat prompt.txt | hey
hey Please explain what this script do. < script.sh
```

To view the conversation history, use:

```shell
hey --history
```

All previous conversations are stored locally, and you can list them with:

```shlel
hey --list
```

Search past conversations using a keyword:

```shell
hey --search [Keyword]
```

Switch back to a previous context like this:

```shell
hey --switch [Context ID]
```

If you no longer need a conversation, delete it with:

```shell
hey --delete --context [Context ID]
```


## Usage

```text
❯ hey --help
usage: hey [-h] [-n [NEW]] [-c CONTEXT] [-H] [-l [LIST]] [-q SEARCH] [--delete] [-s SWITCH] [--undo] [--rename RENAME] [--plain] [-m MODEL] [-t TEMPERATURE]
           [--no-stream] [-p PROFILE] [--config CONFIG] [-v]
           [inputs ...]

positional arguments:
  inputs                input messages

options:
  -h, --help            show this help message and exit
  -n [NEW], --new [NEW]
                        create a new context (with optional context name)
  -c CONTEXT, --context CONTEXT
                        context id
  -H, --history         show history
  -l [LIST], --list [LIST]
                        list contexts (with optional range parameter: [start:end])
  -q SEARCH, --search SEARCH
                        search contexts
  --delete              delete context
  -s SWITCH, --switch SWITCH
                        switch context
  --undo                delete last message and response
  --rename RENAME       rename context
  --plain               plain text mode
  -m MODEL, --model MODEL
                        model name
  -t TEMPERATURE, --temperature TEMPERATURE
                        sampling temperature
  --no-stream           disable streaming
  -p PROFILE, --profile PROFILE
                        profile name
  --config CONFIG       path to config file
  -v, --version         show program's version number and exit
```

## Configuration

Through the `~/.hey/config.yml` file, users can manage their environment settings and profiles for different use cases.

The config.yml file is structured as follows:

```yaml
profiles:
  default:                              # This is the default configuration used when no --profile is explicitly specified.
    model: gpt-4                        # Name of the model to use
    temperature: 0                      # Sampling parameter
    prompt:                             # Specify a default prompt (optional)
    - role: system
      content: ...

  lmstudio:
    base_url: http://localhost:1234/v1  # Base URL for the API
    api_key: not-needed                 # API key
    model: local-model                  # Model to use for this profile
```
