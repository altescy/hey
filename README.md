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
pipx install git+https://github.com/altescy/hey
```

## Usage

```text
❯ hey --help
usage: hey [-h] [--new [NEW]] [--context CONTEXT] [--history] [--list [LIST]] [--search SEARCH] [--delete]
           [--switch SWITCH] [--undo] [--rename RENAME] [--plain] [--model MODEL] [--temperature TEMPERATURE]
           [--profile PROFILE] [--config CONFIG] [--version]
           [inputs ...]

positional arguments:
  inputs                input messages

options:
  -h, --help            show this help message and exit
  --new [NEW]           create a new context (with optional context name)
  --context CONTEXT     context id
  --history             show history
  --list [LIST]         list contexts (with optional range parameter: [start:end])
  --search SEARCH       search contexts
  --delete              delete context
  --switch SWITCH       switch context
  --undo                delete last message and response
  --rename RENAME       rename context
  --plain               plain text mode
  --model MODEL         model name
  --temperature TEMPERATURE
                        sampling temperature
  --profile PROFILE     profile name
  --config CONFIG       path to config file
  --version             show program's version number and exit
```
