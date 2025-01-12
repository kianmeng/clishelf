# ------------------------------------------------------------------------------
# Copyright (c) 2022 Korawich Anuttra. All rights reserved.
# Licensed under the MIT License. See LICENSE in the project root for
# license information.
# ------------------------------------------------------------------------------
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

import click

from .git import CommitLog
from .settings import BumpVerConf

cli_vs: click.Command
GroupCommitLog = Dict[str, List[CommitLog]]
TagGroupCommitLog = Dict[str, GroupCommitLog]


def gen_group_commit_log(all_tags: bool = False) -> GroupCommitLog:
    """Generate Group of the Commit Logs

    :rtype: GroupCommitLog
    """
    from .git import get_commit_logs

    tag_group_logs: TagGroupCommitLog = defaultdict(lambda: defaultdict(list))
    for log in get_commit_logs(
        all_logs=all_tags,
        excluded=[
            r"pre-commit autoupdate",
            r"^Merge",
        ],
    ):
        tag_group_logs[log.refs][log.msg.mtype].append(log)
    rs: TagGroupCommitLog = {}
    for ref_tag in tag_group_logs:
        rs[ref_tag] = {
            k: sorted(v, key=lambda x: x.date, reverse=True)
            for k, v in tag_group_logs[ref_tag].items()
        }
    return rs


def get_changelog(
    file: str,
    tags: Optional[List[str]] = None,
    refresh: bool = False,
):
    changes: List[str]
    if refresh or not Path(file).exists():
        from more_itertools import roundrobin

        _changes = ["# Changelogs", "## Latest Changes"]
        if tags:
            _changes.extend(f"## {t}" for t in tags)
        changes = roundrobin(_changes, ([""] * (len(_changes) - 1)))
    else:
        with Path(file).open(mode="r", encoding="utf-8") as f_changes:
            changes = f_changes.read().splitlines()
    return changes


def writer_changelog(
    file: str,
    all_tags: bool = False,
    refresh: bool = False,
) -> None:
    """Writer Changelog."""
    group_logs: GroupCommitLog = gen_group_commit_log(all_tags=all_tags)
    tags: List[str] = list(filter(lambda t: t != "HEAD", group_logs.keys()))

    changes = get_changelog(file, tags=tags, refresh=refresh)

    with Path(file).open(mode="w", encoding="utf-8", newline="") as writer:
        skip_line: bool = False
        for line in changes:
            if line.startswith("## Latest Changes"):
                write_group_log(
                    writer,
                    group_logs.get("HEAD", {}),
                    tag_value="Latest Changes",
                )
                skip_line = True
            elif m := re.match(rf"^##\s({BumpVerConf.regex})", line):
                get_tag: str = m.group(1)
                if get_tag in tags:
                    write_group_log(
                        writer,
                        group_logs[get_tag],
                        tag_value=get_tag,
                    )
                    skip_line = True
                else:
                    skip_line = False
            elif line.startswith("## "):
                skip_line = False

            if not skip_line:
                writer.write(line + os.linesep)


def write_group_log(writer, group_logs, tag_value: str):
    from .settings import GitConf

    linesep: str = os.linesep
    if not group_logs or any(
        cpt[0] in group_logs for cpt in GitConf.commit_prefix_group
    ):
        linesep = f"{os.linesep}{os.linesep}"

    writer.write(f"## {tag_value}{linesep}")

    for group in (
        cpt[0] for cpt in GitConf.commit_prefix_group if cpt[0] in group_logs
    ):
        writer.write(f"### {group}{os.linesep}{os.linesep}")
        for log in group_logs[group]:
            writer.write(
                f"- {log.msg.content} (_{log.date:%Y-%m-%d}_){os.linesep}"
            )
        writer.write(os.linesep)


def write_bump_file(
    file: str,
    changelog_file: str,
    *,
    version: int = 1,
) -> None:
    """Writing the ``.bump2version.cfg`` config file at current path."""
    with Path(".bumpversion.cfg").open(mode="w", encoding="utf-8") as f_bump:
        f_bump.write(
            BumpVerConf.get_version(
                version,
                params={
                    "changelog": changelog_file,
                    "version": current_version(file),
                    "file": file,
                },
            )
        )


def bump2version(
    action: str,
    file: str,
    changelog_file: str,
    changelog_ignore: bool = False,
    dry_run: bool = False,
    version: int = 1,
):
    """Bump version process."""
    # Start writing ``.bump2version.cfg`` file on current path.
    write_bump_file(file, changelog_file, version=version)

    if not changelog_ignore:
        writer_changelog(file=changelog_file)

    # COMMIT: commit add config and edit changelog file.
    subprocess.run(["git", "add", "-A"])
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "build: add bump2version config file",
            "--no-verify",
        ],
        stdout=subprocess.DEVNULL,
    )
    click.echo("Start write '.bump2version.cfg' config file ...")
    subprocess.run(
        [
            "bump2version",
            action,
            "--commit-args=--no-verify",
        ]
        + (["--list", "--dry-run"] if dry_run else [])
    )

    subprocess.run(
        [
            "git",
            "reset",
            "--soft",
            "HEAD~1",
        ],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )

    # Remove ``.bump2version.cfg`` file.
    Path(".bumpversion.cfg").unlink(missing_ok=False)
    click.echo("Unlink '.bump2version.cfg' config file ...")

    with Path(".git/COMMIT_EDITMSG").open(encoding="utf-8") as f_msg:
        raw_msg = f_msg.read().splitlines()
    subprocess.run(
        [
            "git",
            "commit",
            "--amend",
            "-m",
            raw_msg[0],
            "--no-verify",
        ],
        stderr=subprocess.DEVNULL,
    )


def current_version(file: str) -> str:
    with Path(file).open(encoding="utf-8") as f:
        if search := re.search(BumpVerConf.regex, f.read()):
            return search[0]
    raise NotImplementedError(f"{file} does not implement version value.")


def load_project() -> Dict[str, Any]:
    from .utils import load_pyproject

    return load_pyproject().get("project", {})


def load_config() -> Dict[str, Any]:
    """Return config of the shelf package that was set on pyproject.toml."""
    from .utils import load_pyproject

    return load_pyproject().get("tool", {}).get("shelf", {}).get("version", {})


@click.group(name="vs")
def cli_vs():
    """The Versioning commands."""
    pass  # pragma: no cover.


@cli_vs.command()
def conf() -> NoReturn:
    """Return the config data for bumping version."""
    for k, v in load_config().items():
        click.echo(f"{k}: {v!r}")
    sys.exit(0)


@cli_vs.command()
@click.option("-f", "--file", type=click.Path(exists=True))
@click.option("-n", "--new", is_flag=True)
def changelog(
    file: Optional[str],
    new: bool,
) -> NoReturn:
    """Make Changelogs file"""
    if not file:
        file: str = load_config().get("changelog", None) or "CHANGELOG.md"
    if new:
        writer_changelog(file, all_tags=True, refresh=new)
        sys.exit(0)
    writer_changelog(file, refresh=new)
    sys.exit(0)


@cli_vs.command()
@click.option(
    "-f",
    "--file",
    type=click.Path(exists=True),
    help="The contain version file that able to search with regex.",
)
def current(file: str) -> NoReturn:
    """Return Current Version that read from ``__about__`` by default."""
    if not file:
        file = load_config().get("version", None) or (
            f"./{load_project().get('name', 'unknown')}/__about__.py"
        )
    click.echo(current_version(file))
    sys.exit(0)


@cli_vs.command()
@click.option(
    "-p",
    "--push",
    is_flag=True,
    help="If True, it will push the tag to remote repository",
)
def tag(push: bool) -> NoReturn:
    """Create the Git tag by version from the ``__about__`` file.

    \f
    :param push: A push flag that will push the tag to remote if it True.
    :type push: boolean
    """
    from .__about__ import __version__

    subprocess.run(["git", "tag", f"v{__version__}"])
    if push:
        subprocess.run(["git", "push", "--tags"])


@cli_vs.command()
@click.argument("action", type=click.STRING, required=1)
@click.option(
    "-f",
    "--file",
    type=click.Path(exists=True),
    help="A about file path that want to write new version.",
)
@click.option(
    "-c",
    "--changelog-file",
    type=click.Path(exists=True),
    help="A changelog file path that want to write new version.",
)
@click.option(
    "-v",
    "--version",
    type=click.INT,
    default=1,
    help="A version of bump2version config, it default by 1.",
)
@click.option(
    "--ignore-changelog",
    is_flag=True,
    help="If True, it will skip writing changelog step before bump version.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="If True, it will pass --dry-run option to bump2version",
)
def bump(
    action: str,
    file: Optional[str],
    changelog_file: Optional[str],
    version: int,
    ignore_changelog: bool,
    dry_run: bool,
) -> NoReturn:
    """Bump Version with specific action.

    ACTION is the part of action that should be `major`, `minor`, or `patch`.

    \f
    :param action: A action path for bump the next version.
    :type action: str
    :param file: Optional[str]
    :param changelog_file: Optional[str]
    :param version: int
    :param ignore_changelog: Ignore the changelog file if set be True.
    :type ignore_changelog: boolean
    :param dry_run: Dry run the bumpversion command if set be True.
    :type dry_run: boolean
    """
    if not file:
        file: str = load_config().get("version", None) or (
            f"./{load_project().get('name', 'unknown')}/__about__.py"
        )
    if not changelog_file:
        changelog_file: str = (
            load_config().get("changelog", None) or "CHANGELOG.md"
        )
    bump2version(
        action,
        file,
        changelog_file,
        ignore_changelog,
        dry_run,
        version,
    )
    sys.exit(0)


if __name__ == "__main__":
    cli_vs.main()
