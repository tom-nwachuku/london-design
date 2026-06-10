"""Pure data banks for the deterministic OfflineDirector."""

from __future__ import annotations

from dataclasses import dataclass

ROUTE_SYNTHESIS_PROVIDER = "local-session"
# The offline origin marker — lands ONLY in receipts/debug (D-06 "no-model template
# preview"), NEVER in any creative-prose field. ``session.py`` stamps this into the
# route-synthesis receipt so the offline path is auditable without tainting copy.
OFFLINE_ORIGIN_MARKER = "offline-template-preview"


# --- Stage-1 dataclasses (relocated verbatim from session.py) ---


@dataclass(frozen=True)
class RouteSeed:
    title: str
    headline: str
    subhead: str
    tags: tuple[str, ...]
    lore: str
    mood: str
    type_note: str
    rationale: str
    steal: tuple[str, ...]
    do_not_copy: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CategoryProfile:
    slug: str
    label: str
    keywords: tuple[str, ...]
    product_noun: str
    audience: str
    aesthetic_void: str
    category_assumption: str
    london_reframe: str
    vessel_expression: str
    recurring_loop: str
    unboxing: str
    anti_position: str
    voice: str
    aesthetic: str
    type_system: str
    color_system: str
    palette: tuple[dict[str, str], ...]
    source_terms: str
    image_direction: str
    shot_list: tuple[str, ...]
    generation_constraints: tuple[str, ...]
    motion_principles: tuple[str, ...]
    risks: tuple[str, ...]
    route_seeds: tuple[RouteSeed, ...]


@dataclass(frozen=True)
class SessionLane:
    slug: str
    label: str
    origin: str
    product_noun: str
    audience: str
    jobs: tuple[str, ...]
    rituals: tuple[str, ...]
    surfaces: tuple[str, ...]
    tensions: tuple[str, ...]
    tone: tuple[str, ...]
    avoid: tuple[str, ...]
    output_moments: tuple[str, ...]
    aesthetic_void: str
    category_assumption: str
    london_reframe: str
    vessel_expression: str
    recurring_loop: str
    unboxing: str
    anti_position: str
    voice: str
    aesthetic: str
    type_system: str
    color_system: str
    palette: tuple[dict[str, str], ...]
    source_terms: str
    image_direction: str
    shot_list: tuple[str, ...]
    generation_constraints: tuple[str, ...]
    motion_principles: tuple[str, ...]
    risks: tuple[str, ...]
    route_seeds: tuple[RouteSeed, ...]


CreativeLane = CategoryProfile | SessionLane


PROFILES: tuple[CategoryProfile, ...] = (
    CategoryProfile(
        slug="enterprise-compliance",
        label="Enterprise Compliance System",
        keywords=("hr", "human resources", "compliance", "enterprise", "policy", "audit", "risk", "workforce", "employee"),
        product_noun="compliance workflow",
        audience="HR, legal, and operations teams who need proof without a fear-soaked interface.",
        aesthetic_void="Enterprise compliance usually looks like a punishment: gray dashboards, legal anxiety, and no sense of ritual around proof.",
        category_assumption="Compliance software is a dashboard for avoiding mistakes.",
        london_reframe="Make compliance feel like an evidence studio: calm, legible, and built around proof that travels.",
        vessel_expression="The interface behaves like an audit binder made digital: indexed trails, stamped decisions, policy cards, and calm escalation states.",
        recurring_loop="policy change -> evidence capture -> review trail -> renewal reminder",
        unboxing="The first moment is a clean proof packet: what changed, who approved it, what evidence is attached.",
        anti_position="Not cyberpunk risk theater, not generic SaaS blue, not a wall of compliance cards.",
        voice="This should feel like the grown-up in the room, not the software equivalent of a panic email.",
        aesthetic="governance grotesk, archive utility, evidence-first enterprise calm",
        type_system="A governance grotesk for navigation and a tight mono for evidence IDs, timestamps, and audit receipts.",
        color_system="Deep ink, quiet paper, signal green, amber escalation, and steel blue used as status language rather than decoration.",
        palette=(
            {"role": "ink", "name": "Policy Ink", "hex": "#17212b"},
            {"role": "paper", "name": "Audit Paper", "hex": "#f4f1e8"},
            {"role": "proof", "name": "Evidence Green", "hex": "#2d8f6f"},
            {"role": "warning", "name": "Escalation Amber", "hex": "#d59f2a"},
            {"role": "system", "name": "Ledger Blue", "hex": "#5a7fa6"},
        ),
        source_terms="dashboard app flow governance guidelines brand system audit proof enterprise UI",
        image_direction="Show documents, review states, sign-off moments, and evidence packets. No handshake stock and no abstract lock icons.",
        shot_list=("Policy packet hero", "Reviewer queue", "Stamped approval trail", "Exception escalation", "Exported audit receipt"),
        generation_constraints=("No generic business stock", "No glowing shields", "No fake legal jargon as decoration"),
        motion_principles=("Status changes stamp into place", "Audit trail expands vertically", "Evidence cards pin while decisions scroll"),
        risks=("Can become too cold if every surface is a table", "Can look like security software if the palette gets too blue"),
        route_seeds=(
            RouteSeed(
                title="Audit Trail Atlas",
                headline="Turn policy work into a map of proof.",
                subhead="A calm evidence system where every action leaves a legible trail.",
                tags=("enterprise trust", "audit trail", "proof packet"),
                lore="The product is not a dashboard. It is the place where a messy organization becomes legible.",
                mood="Calm, precise, institutional, with one warm signal color for human judgment.",
                type_note="Use a compact grotesk for commands and mono labels for evidence IDs.",
                rationale="London would make the boring proof layer visible and treat it like the object of the product.",
                steal=("Steal the clarity of archival systems.", "Use stamps, indexes, and trails as interface grammar."),
                do_not_copy=("Do not borrow bank-brand blue as a personality.", "Do not hide everything behind generic cards."),
                sections=(
                    ("Proof Packet Hero", "Lead with what changed, who approved it, and what evidence is already attached."),
                    ("Policy Trail", "Show the living chain of documents, reviewers, deadlines, and exception notes."),
                    ("Audit Export", "Close with a shareable receipt that makes compliance travel outside the app."),
                ),
            ),
            RouteSeed(
                title="Calm Exception Desk",
                headline="Make the scary cases feel handled.",
                subhead="A workflow route built around triage, evidence, and confident escalation.",
                tags=("risk triage", "calm ops", "review desk"),
                lore="This is the compliance desk as a designed ritual: intake, assess, approve, prove.",
                mood="Quiet, procedural, reassuring, never decorative.",
                type_note="Pair a legible UI sans with tabular figures and receipt-like metadata.",
                rationale="The route wins by making the exception state the most designed part of the system.",
                steal=("Use queue rhythm as narrative.", "Make escalation states visually distinct but not hysterical."),
                do_not_copy=("Do not make risk look like a sci-fi threat map.", "Do not flatten every decision into the same button."),
                sections=(
                    ("Exception Intake", "Surface severity, owner, deadline, and missing proof in one composed view."),
                    ("Decision Table", "Turn review into a sequence of readable, signed decisions."),
                    ("Renewal Loop", "Show how the system keeps policies fresh after the crisis has passed."),
                ),
            ),
        ),
    ),
    CategoryProfile(
        slug="kids-lunchbox",
        label="Kid-Owned Food Ritual",
        keywords=("kid", "kids", "child", "children", "lunch", "lunchbox", "school", "snack", "parent", "family"),
        product_noun="lunchbox system",
        audience="Parents who pack lunch and kids who want the object to feel like theirs.",
        aesthetic_void="Lunch products either talk to parents like chore software or to kids like disposable cartoon packaging.",
        category_assumption="A lunchbox is a container parents fill before school.",
        london_reframe="Make lunch a kid-owned daily ritual: choice, reveal, trade, clean-up, repeat.",
        vessel_expression="The object needs compartments, labels, stickers, color-coded decisions, and a reveal moment when the lid opens.",
        recurring_loop="weekly pack plan -> kid choice -> lunch reveal -> sticker/reward refresh",
        unboxing="The first moment is the lid opening into a tiny field kit: sections, labels, and a color-coded choice game.",
        anti_position="Not beige parent wellness, not licensed-character landfill, not an app pretending to be lunch.",
        voice="Give the child authorship and the parent relief. The product should feel useful before it feels cute.",
        aesthetic="playful school utility, sticker ritual, bright field-guide food system",
        type_system="A rounded utility sans for parent clarity, with hand-label accents for kid ownership.",
        color_system="Lunch yellow, tomato red, crayon blue, fresh green, and warm cream, each tied to a food or choice state.",
        palette=(
            {"role": "sun", "name": "Lunchbox Yellow", "hex": "#f6c445"},
            {"role": "paper", "name": "Snack Cream", "hex": "#fff4d7"},
            {"role": "fruit", "name": "Tomato Sticker", "hex": "#e84b3c"},
            {"role": "choice", "name": "Crayon Blue", "hex": "#3277c9"},
            {"role": "fresh", "name": "Snap Pea", "hex": "#58a55c"},
        ),
        source_terms="packaging school food kids retail illustration product photography commerce",
        image_direction="Use overhead packing rituals, compartment reveals, hand labels, fruit color, and school-morning light.",
        shot_list=("Open lunchbox reveal", "Kid choosing stickers", "Parent prep rail", "Backpack side pocket", "Clean-up ritual"),
        generation_constraints=("No generic smiling cafeteria stock", "No licensed character lookalikes", "No beige wellness kitchen haze"),
        motion_principles=("Compartments reveal one by one", "Sticker states snap into place", "Weekly plan scrolls like a field guide"),
        risks=("Can become childish for parents if utility disappears", "Can become parent productivity if kid authorship disappears"),
        route_seeds=(
            RouteSeed(
                title="Sticker Ritual Kit",
                headline="Let kids claim lunch before they eat it.",
                subhead="A bright, modular route where stickers, compartments, and choice make the object repeatable.",
                tags=("kid ownership", "food ritual", "packaging system"),
                lore="The lunchbox becomes a tiny daily publishing system: today has a label, a color, and a reveal.",
                mood="Bright, organized, tactile, and a little mischievous.",
                type_note="Rounded sans for parent scanning; hand-label moments for kid authorship.",
                rationale="London would make the recurring behavior visible instead of selling another cute container.",
                steal=("Steal the logic of school supplies.", "Make stickers a state system, not decoration."),
                do_not_copy=("Do not make it look like a licensed cartoon product.", "Do not bury food under lifestyle props."),
                sections=(
                    ("Lid Reveal", "Open with compartments, labels, and one kid-made choice visible immediately."),
                    ("Pack Together", "Show parent prep as a fast ritual with color-coded decisions."),
                    ("Sticker Loop", "Make refresh packs and weekly themes the recurring product behavior."),
                ),
            ),
            RouteSeed(
                title="Lunchbox Field Guide",
                headline="A school-day kit for tiny decisions.",
                subhead="A more instructional route that treats lunch as a field guide, not a chore.",
                tags=("field guide", "school utility", "daily choice"),
                lore="Every piece has a job: map, choose, pack, reveal, clean.",
                mood="Useful, sunny, diagrammatic, less cute than expected.",
                type_note="Use field-guide captions, large numbers, and friendly utility labels.",
                rationale="The route turns ordinary food prep into a repeatable product system parents can trust.",
                steal=("Use diagram language from manuals.", "Make every compartment explain itself without a paragraph."),
                do_not_copy=("Do not turn the page into a recipe blog.", "Do not make the kid moment secondary."),
                sections=(
                    ("Choice Map", "Show the lunch as a simple map of crunch, sweet, fresh, and main."),
                    ("School Proof", "Frame the object in backpack, desk, and cleanup contexts."),
                    ("Refill Ritual", "Close on stickers, dividers, and seasonal prompts as the recurring loop."),
                ),
            ),
        ),
    ),
    CategoryProfile(
        slug="luxury-fragrance",
        label="Fragrance Ritual Object",
        keywords=("fragrance", "perfume", "scent", "luxury", "olfactory", "bottle", "atelier", "compact", "solid fragrance"),
        product_noun="fragrance ritual",
        audience="Taste-led buyers who treat scent as an object, a memory, and a private ritual.",
        aesthetic_void="Fragrance launches keep choosing between sterile luxury minimalism and fake sensual smoke.",
        category_assumption="Fragrance is a mood, a bottle, and a list of notes.",
        london_reframe="Make scent an object-led ritual: material, gesture, refill, memory, display.",
        vessel_expression="The compact or bottle must carry the thesis through weight, hinge, label, refill, and the way it sits in the hand.",
        recurring_loop="scent ritual -> refill -> seasonal note -> display object",
        unboxing="The first moment is a quiet reveal of material, note card, refill logic, and skin-close use.",
        anti_position="Not black-box luxury cosplay, not Sephora template, not a vague cloud of sensual adjectives.",
        voice="If the vessel is forgettable, the fragrance is already losing. Make the object do the talking.",
        aesthetic="quiet atelier, material ritual, editorial luxury with object proof",
        type_system="A high-contrast serif for scent lore, restrained grotesk for ingredients, and tiny mono for batch/refill details.",
        color_system="Ink black, warm vellum, aged gold, oxblood, and smoke gray, used with restraint and material contrast.",
        palette=(
            {"role": "ink", "name": "Atelier Black", "hex": "#14110f"},
            {"role": "paper", "name": "Vellum", "hex": "#efe4cf"},
            {"role": "metal", "name": "Aged Gold", "hex": "#b78945"},
            {"role": "note", "name": "Oxblood Resin", "hex": "#6f1f2a"},
            {"role": "air", "name": "Smoke Glass", "hex": "#6c716f"},
        ),
        source_terms="fragrance packaging luxury retail bottle editorial photography commerce dieline",
        image_direction="Use macro material shots, hand-applied ritual, box interiors, note cards, and quiet shelf presence.",
        shot_list=("Vessel macro", "Hand applying scent", "Box compartment reveal", "Note card spread", "Refill close-up"),
        generation_constraints=("No generic perfume bottle render", "No smoky stock portrait", "No sterile white luxury page"),
        motion_principles=("Material reveals slowly", "Notes layer like cards", "Refill mechanism gets one precise interaction"),
        risks=("Can become generic luxury if material proof is weak", "Can over-write scent lore instead of showing object behavior"),
        route_seeds=(
            RouteSeed(
                title="Quiet Atelier",
                headline="Make the vessel feel inevitable.",
                subhead="A restrained material route centered on compact, note card, refill, and hand ritual.",
                tags=("fragrance object", "material ritual", "quiet luxury"),
                lore="The scent lives in a small private architecture: hinge, wax, note, hand, pocket.",
                mood="Quiet, tactile, intimate, expensive because it is specific.",
                type_note="High-contrast serif for lore; restrained grotesk for product truth.",
                rationale="London would make the vessel the argument and let the page behave like a product table.",
                steal=("Steal the discipline of luxury packaging compartments.", "Use note cards as page rhythm."),
                do_not_copy=("Do not copy black-box perfume tropes.", "Do not use smoke as a substitute for art direction."),
                sections=(
                    ("Object Hero", "Lead with the compact or bottle as a material thing, not a fantasy cloud."),
                    ("Skin Ritual", "Show the exact gesture of applying, closing, and carrying the scent."),
                    ("Refill Logic", "Make recurring purchase feel like care for the object, not subscription pressure."),
                ),
            ),
            RouteSeed(
                title="Night Bottle Ritual",
                headline="Turn the scent notes into a physical sequence.",
                subhead="A richer editorial route where note, vessel, and box interior move together.",
                tags=("night ritual", "scent notes", "editorial packaging"),
                lore="The launch feels like opening a drawer in a private club: few words, strong materials, exact hierarchy.",
                mood="Darker, slower, more ceremonial, but still product-first.",
                type_note="Use serif display sparingly, with batch-code details that make the system feel real.",
                rationale="The route makes the scent story tangible through compartments, cards, and refill proof.",
                steal=("Use box architecture as storytelling.", "Make each note a tactile artifact."),
                do_not_copy=("Do not become a fashion fragrance template.", "Do not let copy outpace the object."),
                sections=(
                    ("Note Sequence", "Present top, heart, and base as objects or cards in a deliberate order."),
                    ("Material Proof", "Show hinge, cap, wax, glass, label, and shadow with macro restraint."),
                    ("Display Finish", "Close with the object at rest, proving it belongs on a shelf."),
                ),
            ),
        ),
    ),
    CategoryProfile(
        slug="public-horoscope",
        label="Public Horoscope Ritual App",
        keywords=(
            "horoscope",
            "astrology",
            "zodiac",
            "birth chart",
            "natal",
            "compatibility",
            "synastry",
            "moon",
            "rising sign",
            "daily reading",
            "push notification",
            "shareable",
        ),
        product_noun="horoscope app",
        audience="Astrology-curious consumers, creators, and friend groups who want a daily ritual that feels specific enough to share.",
        aesthetic_void="Public astrology apps keep collapsing into purple wellness fog, vague affirmation feeds, or cynical notification bait.",
        category_assumption="A horoscope app is a daily content feed with zodiac symbols and mystical gradients.",
        london_reframe="Make astrology feel like a morning briefing with emotional texture: chart weather, social proof, share cards, and clear caveats.",
        vessel_expression="The app is a pocket almanac: daily sign-in card, chart dial, compatibility receipt, and a shareable visual reading that feels authored.",
        recurring_loop="birth-chart onboarding -> daily sign-in -> friend/share moment -> moon or transit ritual",
        unboxing="The first moment is a precise birth-chart intake that explains why the reading will be specific, not a vague fortune-cookie feed.",
        anti_position="Not generic mystical purple wellness, not scammy certainty, not a zodiac meme account wearing product clothes.",
        voice="London would make the app admit what it knows, what it infers, and why the ritual is worth returning to tomorrow.",
        aesthetic="cinematic almanac, social astrology, morning ritual, skepticism-aware cosmic utility",
        type_system="A literary serif for readings, a crisp app sans for actions, and small mono or tabular labels for chart degrees and transit receipts.",
        color_system="Midnight ink, moon paper, solar amber, chart blue, and aura coral, each tied to a reading state rather than generic mystic mood.",
        palette=(
            {"role": "ink", "name": "Midnight Ink", "hex": "#111827"},
            {"role": "paper", "name": "Moon Paper", "hex": "#f6ead7"},
            {"role": "sun", "name": "Solar Amber", "hex": "#f2b84b"},
            {"role": "chart", "name": "Chart Blue", "hex": "#3f6f9f"},
            {"role": "social", "name": "Aura Coral", "hex": "#e66f5c"},
        ),
        source_terms="astrology app daily ritual consumer social cards onboarding typography mobile interface",
        image_direction="Use morning phone moments, chart wheels, friend-share cards, notification rituals, and cinematic almanac textures. Keep symbols useful, not decorative fog.",
        shot_list=("Daily reading card", "Birth-chart onboarding", "Compatibility share card", "Morning notification", "Moon transit calendar"),
        generation_constraints=(
            "No purple wellness gradient soup",
            "No fake occult certainty",
            "No stock hands holding a glowing phone",
        ),
        motion_principles=(
            "Daily card turns over like a small ritual",
            "Chart details reveal by degree and house",
            "Share cards export with one tap and a visible caveat",
        ),
        risks=(
            "Can feel scammy if every claim is too certain",
            "Can feel like a meme app if social sharing replaces emotional specificity",
        ),
        route_seeds=(
            RouteSeed(
                title="Morning Sign-In",
                headline="Treat the horoscope like emotional weather, not prophecy.",
                subhead="A daily ritual route where the user opens a precise, caveated reading before the day gets loud.",
                tags=("daily ritual", "chart weather", "skepticism-aware"),
                lore="The app becomes a pocket almanac: one daily card, one transit reason, one suggested move.",
                mood="Cinematic, intimate, legible, and calm enough to be trusted at 7am.",
                type_note="Literary serif for the reading; crisp sans and tiny tabular labels for chart proof.",
                rationale="London would make specificity the product: the reading should show its inputs instead of hiding behind mystic vibes.",
                steal=("Steal the rhythm of a weather app.", "Use chart receipts as proof, not ornament."),
                do_not_copy=("Do not sell certainty the product cannot earn.", "Do not make the page a purple affirmation feed."),
                sections=(
                    ("Daily Card", "Lead with today's sign-specific reading, one chart reason, and a clear confidence/caveat line."),
                    ("Chart Weather", "Show the transits, moon phase, and house focus as small proof tags beneath the reading."),
                    ("Morning Ritual", "End with a push-notification moment and one shareable action for the day."),
                ),
            ),
            RouteSeed(
                title="Compatibility Card Studio",
                headline="Make astrology social without making it shallow.",
                subhead="A share-card route for friend groups, compatibility reads, and creator-friendly visual rituals.",
                tags=("social astrology", "compatibility", "share cards"),
                lore="The app turns readings into receipts people can send: a little intimate, a little funny, still legible.",
                mood="More graphic, social, and kinetic, with enough structure to avoid meme mush.",
                type_note="Strong sans for card headlines, softer serif snippets for the reading, and small proof labels for chart inputs.",
                rationale="The route wins by making sharing feel like a designed artifact, not a screenshot of text.",
                steal=("Use editorial card systems for shareability.", "Make compatibility outputs feel inspectable and emotionally specific."),
                do_not_copy=("Do not become a zodiac meme template.", "Do not bury the caveat behind social polish."),
                sections=(
                    ("Friend Pairing", "Open with two charts, one compatibility thesis, and visible inputs."),
                    ("Share Card Rail", "Show cards for mood, tension, timing, and advice with export-ready compositions."),
                    ("Group Ritual", "Close on friend-thread prompts and recurring moon/transit moments."),
                ),
            ),
        ),
    ),
    CategoryProfile(
        slug="tactile-product",
        label="Tactile Product System",
        keywords=("retro", "futurist", "retro-futurist", "joyful", "tactile", "hardware", "object", "product", "packaging"),
        product_noun="tactile product",
        audience="Design-literate buyers who notice the product, packaging, and page as one system.",
        aesthetic_void="Product launches keep oscillating between sterile minimalism and nostalgia wallpaper.",
        category_assumption="A product launch is a feature list with a nice hero render.",
        london_reframe="Make the object, package, and page prove one point of view before the feature list arrives.",
        vessel_expression="Transparent details, oversized inspection frames, color-coded states, and packaging that behaves like interface.",
        recurring_loop="route -> visual proof -> prototype -> quality receipt",
        unboxing="The first moment frames the object like a collectible tool with instructions worth keeping.",
        anti_position="Not generic modern clean, not stock-photo lifestyle haze, not copied gallery taste.",
        voice="The page should make the object feel designed before anyone reads a spec.",
        aesthetic="joyful retro-futurist product proof with tactile hardware cues",
        type_system="Wide utility grotesk for product claims, warmer editorial accents for collector-grade moments.",
        color_system="Signal orange, warm paper, mint circuit, soft black, and hardware yellow as product-state language.",
        palette=(
            {"role": "spark", "name": "Signal Orange", "hex": "#ff6b35"},
            {"role": "ground", "name": "Warm Paper", "hex": "#f7f1df"},
            {"role": "accent", "name": "Mint Circuit", "hex": "#56c7b6"},
            {"role": "ink", "name": "Soft Black", "hex": "#151515"},
            {"role": "glow", "name": "Hardware Yellow", "hex": "#ffd447"},
        ),
        source_terms="hardware product packaging web composition typography color retro futurist",
        image_direction="Use product-forward previews, visible materials, packaging inserts, hand scale, and one strange color behavior.",
        shot_list=("Hero object inspection", "Material detail", "Packaging insert", "Hand interaction", "Shelf finish"),
        generation_constraints=("No generic stock lifestyle haze", "No nostalgia wallpaper", "No purple-blue AI gradients"),
        motion_principles=("Product frame pins first", "Color states respond to use", "Packaging grid drives scroll sections"),
        risks=("Can drift into toy-like novelty", "Can overuse retro styling without product behavior"),
        route_seeds=(
            RouteSeed(
                title="Signal Object Manual",
                headline="Make the product explain itself by being impossible to ignore.",
                subhead="A route built from inspection frames, packaging grids, and one memorable color behavior.",
                tags=("tactile product", "manual rhythm", "retro-futurist"),
                lore="The product behaves like a useful artifact from a sharper future.",
                mood="Optimistic, crisp, tactile, and strange in a controlled way.",
                type_note="Wide grotesk utility with editorial warmth only where the object earns it.",
                rationale="London would make the object truth enormous, then let packaging carry the system.",
                steal=("Use the packaging grid as page grid.", "Make one tactile detail enormous before showing the whole object."),
                do_not_copy=("Do not turn retro into wallpaper.", "Do not hide the product in lifestyle haze."),
                sections=(
                    ("Object Truth", "Show the product large enough to inspect material, scale, and purpose."),
                    ("Use Ritual", "Break the main interaction into a few memorable product states."),
                    ("Shelf Finish", "End with the full kit arranged like packaging someone keeps."),
                ),
            ),
            RouteSeed(
                title="Collector Utility",
                headline="Useful first, collectible because the system has taste.",
                subhead="A calmer graphic route built from labels, states, and restrained product theater.",
                tags=("collector utility", "graphic restraint", "product states"),
                lore="The product arrives with the confidence of a tool and the charm of a kept object.",
                mood="Precise, playful, calmer than the palette suggests.",
                type_note="Condensed labels, readable body copy, and small receipt-like proof details.",
                rationale="The route makes restraint feel expensive by treating every label as part of the product behavior.",
                steal=("Borrow the discipline of manuals.", "Use labels as composition, not annotation."),
                do_not_copy=("Do not make it look like a SaaS dashboard.", "Do not over-explain the joke."),
                sections=(
                    ("Interface Hero", "Lead with a product state and the label that makes it feel owned."),
                    ("Manual Rhythm", "Turn setup and use into art-directed panels."),
                    ("Receipt Finish", "Close with proof: box, insert, label, and one tiny reason to post it."),
                ),
            ),
        ),
    ),
)


# --- Stage-1 vocabulary banks (relocated verbatim from session.py) ---

_SURFACE_TERMS = {
    "app": "app frame",
    "mobile": "mobile frame",
    "phone": "phone frame",
    "dashboard": "dashboard",
    "map": "map view",
    "timeline": "timeline",
    "calendar": "calendar",
    "card": "card system",
    "cards": "card system",
    "notification": "alert",
    "notifications": "alert",
    "alert": "alert",
    "alerts": "alert",
    "profile": "profile",
    "onboarding": "onboarding",
    "packaging": "packaging",
    "compact": "compact object",
    "bottle": "vessel",
    "lunchbox": "object kit",
    "policy": "policy packet",
    "audit": "audit trail",
}

_RITUAL_TERMS = {
    "daily": "daily check",
    "morning": "morning read",
    "weekly": "weekly planning",
    "share": "share",
    "shareable": "share",
    "refill": "refill",
    "refillable": "refill",
    "walk": "walk decision",
    "walking": "walk decision",
    "onboarding": "onboarding",
    "review": "review",
    "reveal": "reveal",
    "pack": "packing",
    "packing": "packing",
    "compliance": "proof review",
    "audit": "proof review",
}

_TONE_TERMS = {
    "luxury": "restrained",
    "quiet": "quiet",
    "joyful": "joyful",
    "playful": "playful",
    "public": "public-facing",
    "enterprise": "calm",
    "safe": "protective",
    "comfortable": "careful",
    "specific": "specific",
    "social": "social",
    "premium": "premium",
    "friendly": "friendly",
}

_PALETTE_BANK: tuple[tuple[str, str, str, str, str], ...] = (
    ("#17212b", "#f4f1e8", "#2d8f6f", "#d59f2a", "#5a7fa6"),
    ("#111827", "#f6ead7", "#f2b84b", "#3f6f9f", "#e66f5c"),
    ("#14110f", "#efe4cf", "#b78945", "#6f1f2a", "#6c716f"),
    ("#20312d", "#f7f1df", "#6fb7c9", "#f0a84a", "#bc5f55"),
    ("#1b2430", "#f8f0dc", "#63a46c", "#3d7ea6", "#e07a5f"),
    ("#231f20", "#fff4d7", "#58a55c", "#3277c9", "#e84b3c"),
)

__all__ = [
    "ROUTE_SYNTHESIS_PROVIDER",
    "OFFLINE_ORIGIN_MARKER",
    "RouteSeed",
    "CategoryProfile",
    "SessionLane",
    "CreativeLane",
    "PROFILES",
    "_SURFACE_TERMS",
    "_RITUAL_TERMS",
    "_TONE_TERMS",
    "_PALETTE_BANK",
]
