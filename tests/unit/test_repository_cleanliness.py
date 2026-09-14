from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def test_legacy_runtime_entrypoints_are_not_in_repository_root():
    retired = {
        "calculate_elo.py",
        "discord_bot.py",
        "bot_database.py",
        "player_stats.py",
        "leaderboard_stats.py",
        "team_config.py",
        "scheduled_updates.py",
        "import_event.py",
        "import_event_v2.py",
        "import_results_v2.py",
        "requirements.txt",
    }
    present = {path.name for path in PROJECT_ROOT.iterdir() if path.is_file()}
    assert retired.isdisjoint(present)


def test_repository_contains_github_and_container_deployment_contracts():
    assert (PROJECT_ROOT / "Dockerfile").is_file()
    assert (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").is_file()
    assert not (PROJECT_ROOT / ".gitlab-ci.yml").exists()
    assert (PROJECT_ROOT / ".env.example").is_file()
