"""本地单用户服务的组件装配入口。"""

import os
from pathlib import Path

from app.agent import AgentRunner, openai_model_factory
from app.api.service import create_app
from app.integrations import UnavailableAdapters
from app.repository import RepositoryAdapters
from app.repository.urls import DEFAULT_ALLOWED_HOSTS
from app.schemas.models import RunConfig
from app.schemas.ports import IntegrationError, Services


def load_config() -> RunConfig:
    return RunConfig(
        model=os.getenv("FVA_MODEL") or "unconfigured",
        temperature=float(os.getenv("FVA_TEMPERATURE", "0")),
        max_output_tokens=int(os.getenv("FVA_MAX_OUTPUT_TOKENS", "2048")),
        max_model_calls=int(os.getenv("FVA_MAX_MODEL_CALLS", "16")),
        max_tool_calls=int(os.getenv("FVA_MAX_TOOL_CALLS", "32")),
        timeout_seconds=float(os.getenv("FVA_TIMEOUT_SECONDS", "120")),
        data_version=os.getenv("FVA_DATA_VERSION"),
        index_version=os.getenv("FVA_INDEX_VERSION"),
    )


def configured_model(config: RunConfig):
    if config.model == "unconfigured" or not os.getenv("OPENAI_API_KEY"):
        raise IntegrationError("model_unconfigured", "请设置 FVA_MODEL 和 OPENAI_API_KEY。")
    return openai_model_factory(config)


def load_allowed_hosts() -> tuple[str, ...]:
    value = os.getenv("FVA_REPOSITORY_HOSTS")
    if not value:
        return DEFAULT_ALLOWED_HOSTS
    hosts = tuple(host.strip().lower() for host in value.split(",") if host.strip())
    return hosts or DEFAULT_ALLOWED_HOSTS


def build_app():
    config = load_config()
    unavailable = UnavailableAdapters()
    repository = RepositoryAdapters(
        os.getenv("FVA_STORAGE_DIR", "storage"),
        allowed_hosts=load_allowed_hosts(),
    )
    services = Services(
        runner=AgentRunner(
            repository=repository,
            retriever=unavailable,
            model_factory=configured_model,
            config=config,
        ),
        preparation=repository,
        exporter=unavailable,
        config=config,
    )
    return create_app(
        services,
        Path(os.getenv("FVA_DB_PATH", "artifacts/tasks.sqlite3")),
        concurrency=int(os.getenv("FVA_CONCURRENCY", "2")),
    )
