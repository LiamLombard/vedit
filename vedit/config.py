from dataclasses import dataclass, asdict
import tomllib
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class Config:
    video_split_secs: int = 60
    speed_multiplier: int = 6

    @staticmethod
    def load(config_file: Path | None = None) -> Self:
        config_file: Path = config_file or Path("config.toml")

        if config_file.exists():
            config = Config(**tomllib.loads(config_file.read_text()))
        else:
            config = Config()
            default_toml = "\n".join(
                f"{key} = {value}" for key, value in asdict(config).items()
            )
            config_file.write_text(default_toml)

        return config
