from __future__ import annotations
from pathlib import Path

from github import Auth, Github, GithubException


class GitHubAuthError(Exception):
    pass


def validate_token(token: str) -> dict:
    """Validate a PAT and return basic account info. Raises GitHubAuthError on 401."""
    try:
        g = Github(auth=Auth.Token(token))
        user = g.get_user()
        login = user.login  # force API call
        return {"login": login, "type": user.type}
    except GithubException as e:
        if e.status == 401:
            raise GitHubAuthError("Invalid or expired GitHub token") from e
        raise


def list_repositories(token: str) -> list[dict]:
    """List all accessible repositories for the token owner."""
    g = Github(auth=Auth.Token(token))
    repos = []
    for repo in g.get_user().get_repos(type="all"):
        repos.append({
            "full_name": repo.full_name,
            "name": repo.name,
            "private": repo.private,
            "default_branch": repo.default_branch,
            "description": repo.description or "",
            "language": repo.language or "",
        })
    return repos


def clone_repository(token: str, full_name: str, target_dir: Path) -> None:
    """Shallow-clone (depth=1) a repository into target_dir."""
    import git  # lazy import — git binary may not be forkable at module load time
    clone_url = f"https://oauth2:{token}@github.com/{full_name}.git"
    git.Repo.clone_from(clone_url, str(target_dir), depth=1, single_branch=True)


def get_file_last_modified(repo_path: Path, file_path: str) -> str | None:
    """Return ISO timestamp of the last commit that touched file_path."""
    try:
        import git  # lazy import
        repo = git.Repo(str(repo_path))
        commits = list(repo.iter_commits(paths=file_path, max_count=1))
        if commits:
            return commits[0].committed_datetime.isoformat()
    except Exception:
        pass
    return None
