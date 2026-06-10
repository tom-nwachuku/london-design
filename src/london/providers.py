from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ProviderKind = Literal["local", "live"]
CapabilityMode = Literal["local", "live", "hybrid"]


@dataclass(frozen=True)
class CapabilitySpec:
    """A public capability London can report without binding to one provider."""

    id: str
    label: str
    mode: CapabilityMode
    description: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderSpec:
    """Provider metadata used by setup checks and future CLI wiring."""

    id: str
    label: str
    kind: ProviderKind
    priority: int
    capabilities: tuple[str, ...]
    env_vars: tuple[str, ...] = ()
    python_modules: tuple[str, ...] = ()
    notes: str = ""

    @property
    def is_keyed(self) -> bool:
        return bool(self.env_vars)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        data["env_vars"] = list(self.env_vars)
        data["python_modules"] = list(self.python_modules)
        data["is_keyed"] = self.is_keyed
        return data


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        id="deterministic_pack",
        label="Deterministic London pack",
        mode="local",
        description="Builds public-safe pack structure without provider keys.",
    ),
    CapabilitySpec(
        id="semantic_london_brain",
        label="Semantic London Brain index",
        mode="local",
        description="Uses Chroma as the derived retrieval path for London's bundled taste brain.",
    ),
    CapabilitySpec(
        id="multimodal_direction",
        label="Multimodal creative direction",
        mode="live",
        description="Reads briefs and visual inputs for design-literate route critique.",
    ),
    CapabilitySpec(
        id="image_generation",
        label="Image generation",
        mode="hybrid",
        description="Generates route imagery through ready local/API providers, or exports honest visual direction boards.",
    ),
    CapabilitySpec(
        id="language_generation",
        label="Language generation",
        mode="live",
        description="Drafts or refines route rationale, dossier copy, and handoff notes.",
    ),
    CapabilitySpec(
        id="web_extraction",
        label="Web extraction",
        mode="live",
        description="Extracts public web references for source packs and audits.",
    ),
    CapabilitySpec(
        id="browser_capture",
        label="Browser capture",
        mode="local",
        description="Captures rendered pages for local prototype and QA evidence.",
    ),
)


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="gemini",
        label="Gemini",
        kind="live",
        priority=50,
        capabilities=("multimodal_direction", "image_generation", "language_generation"),
        env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        notes="Preferred live multimodal and image-generation engine when either Gemini key is configured; image generation uses London direct HTTPS adapter.",
    ),
    ProviderSpec(
        id="local_deterministic",
        label="Local deterministic pack renderer",
        kind="local",
        priority=5,
        capabilities=("deterministic_pack", "semantic_london_brain"),
        notes="Always allowed for pack structure and fixture sketches. It is not treated as real concept art in normal mode.",
    ),
    ProviderSpec(
        id="automatic1111",
        label="Automatic1111",
        kind="local",
        priority=10,
        capabilities=("image_generation",),
        notes="Ready only when the local Stable Diffusion WebUI API answers on /sdapi/v1 and can accept txt2img.",
    ),
    ProviderSpec(
        id="comfyui",
        label="ComfyUI",
        kind="local",
        priority=20,
        capabilities=("image_generation",),
        notes="Ready only when a local ComfyUI server is reachable and LONDON_COMFYUI_WORKFLOW points to workflow JSON.",
    ),
    ProviderSpec(
        id="draw_things",
        label="Draw Things CLI",
        kind="local",
        priority=25,
        capabilities=("image_generation",),
        notes="Recommended free/local Mac path. Ready only when LONDON_DRAW_THINGS_COMMAND can receive a prompt file and output path; detected-only installs still need setup.",
    ),
    ProviderSpec(
        id="external_cmd",
        label="External image command",
        kind="local",
        priority=30,
        capabilities=("image_generation",),
        notes="Bring-your-own local image bridge. Ready when LONDON_EXTERNAL_IMAGE_COMMAND is configured; receipts expose only the command name, never local output paths.",
    ),
    ProviderSpec(
        id="bfl_flux",
        label="BFL / FLUX",
        kind="live",
        priority=70,
        capabilities=("image_generation",),
        env_vars=("BFL_API_KEY",),
        notes="Premium/pro FLUX image generation route. Auto mode uses it only when paid use is explicitly allowed.",
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        kind="live",
        priority=60,
        capabilities=("language_generation", "multimodal_direction", "image_generation"),
        env_vars=("OPENAI_API_KEY",),
        notes="Optional secondary language, multimodal, or image-generation provider; image generation uses London direct HTTPS adapter.",
    ),
    ProviderSpec(
        id="fal",
        label="fal",
        kind="live",
        priority=80,
        capabilities=("image_generation",),
        env_vars=("FAL_KEY", "FAL_API_KEY"),
        notes="Optional FLUX API lane. Selected only when a fal key is configured.",
    ),
    ProviderSpec(
        id="replicate",
        label="Replicate",
        kind="live",
        priority=90,
        capabilities=("image_generation",),
        env_vars=("REPLICATE_API_TOKEN", "REPLICATE_API_KEY"),
        notes="Optional Replicate FLUX lane. Selected only when a Replicate key is configured.",
    ),
    ProviderSpec(
        id="pollinations",
        label="Pollinations",
        kind="live",
        priority=100,
        capabilities=("image_generation",),
        notes="Experimental free network image lane. Disabled unless image.allow_experimental_free_network=true.",
    ),
    ProviderSpec(
        id="perchance",
        label="Perchance",
        kind="live",
        priority=110,
        capabilities=("image_generation",),
        notes="Manual-only prompt export. London must not automate Perchance browser or HTTP access.",
    ),
    ProviderSpec(
        id="manual_prompt",
        label="Visual direction board",
        kind="local",
        priority=120,
        capabilities=("image_generation",),
        notes="Always available as a visual direction board plus copyable route prompt when no ready generator is used.",
    ),
    ProviderSpec(
        id="firecrawl",
        label="Firecrawl",
        kind="live",
        priority=50,
        capabilities=("web_extraction",),
        env_vars=("FIRECRAWL_API_KEY",),
        python_modules=("firecrawl",),
        notes="Optional public web extraction provider for source packs.",
    ),
    ProviderSpec(
        id="playwright",
        label="Playwright",
        kind="local",
        priority=60,
        capabilities=("browser_capture",),
        python_modules=("playwright",),
        notes="Optional local browser capture; install browser binaries separately.",
    ),
)


def provider_registry() -> list[dict[str, object]]:
    return [provider.to_dict() for provider in sorted(PROVIDERS, key=lambda item: item.priority)]


def capability_registry() -> list[dict[str, str]]:
    return [capability.to_dict() for capability in CAPABILITIES]


def provider_by_id(provider_id: str) -> ProviderSpec:
    for provider in PROVIDERS:
        if provider.id == provider_id:
            return provider
    raise KeyError(provider_id)
