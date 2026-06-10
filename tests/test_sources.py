from london.source_packs import (
    build_source_plan,
    list_source_packs,
    recommend_source_lenses,
    recommend_source_packs,
)
from london.sources import (
    ExtractionCandidate,
    classify_source_url,
    extract_showcased_artifact,
    extract_source_artifacts,
    is_gallery_chrome,
    is_showcased_artifact,
    list_sources,
    select_extractable_candidates,
)


def test_source_registry_covers_required_public_sources():
    sources = list_sources()
    names = {source.name for source in sources}

    assert names == {
        "Fonts In Use",
        "Death to Stock",
        "Cosmos",
        "Are.na",
        "It's Nice That",
        "The Brand Identity",
        "The Dieline",
        "BP&O",
        "CARI",
        "Duke Ad Access",
        "Branding Style Guides",
        "Land-book",
        "Godly",
        "Commerce Cream",
        "Mobbin",
        "Cargo",
    }
    assert len({source.slug for source in sources}) == len(sources)
    assert all(source.domains for source in sources)
    assert all(source.disciplines for source in sources)


def test_extractor_accepts_actual_showcased_work_and_detail_artifacts():
    accepted_urls = [
        "https://fontsinuse.com/uses/20234/aesop-logo-website-and-packaging",
        "https://deathtothestockphoto.com/collections/soft-rituals",
        "https://www.cosmos.so/e/quiet-retail-systems",
        "https://www.are.na/london-osei/joyful-retro-futurism",
        "https://www.itsnicethat.com/articles/studio-almanac-graphic-design",
        "https://the-brandidentity.com/project/acme-market",
        "https://thedieline.com/blog/2025/1/7/low-intervention-wine-label-system",
        "https://bpando.org/2025/01/22/brand-identity-for-common-era",
        "https://cari.institute/aesthetics/acidgrafix",
        "https://repository.duke.edu/dc/adaccess/BH0901",
        "https://brandingstyleguides.com/guide/nasa",
        "https://land-book.com/websites/sunday-supply",
        "https://godly.website/website/magnetic-field",
        "https://commercecream.com/brands/glossier",
        "https://mobbin.com/apps/airbnb-ios/screens",
        "https://cargo.site/Index-Space",
    ]

    for url in accepted_urls:
        decision = classify_source_url(url)
        assert decision.accepted, decision
        assert decision.artifact_kind
        assert is_showcased_artifact(url)


def test_extractor_rejects_gallery_container_chrome():
    rejected_urls = [
        "https://fontsinuse.com/uses",
        "https://deathtothestockphoto.com/collections",
        "https://www.cosmos.so/explore",
        "https://www.are.na/search",
        "https://www.itsnicethat.com/graphic-design",
        "https://the-brandidentity.com/projects",
        "https://thedieline.com/blog",
        "https://bpando.org/packaging",
        "https://cari.institute/aesthetics",
        "https://repository.duke.edu/dc/adaccess",
        "https://brandingstyleguides.com/guides",
        "https://land-book.com/websites",
        "https://godly.website/websites",
        "https://commercecream.com/categories/beauty",
        "https://mobbin.com/browse",
        "https://cargo.site/templates",
    ]

    for url in rejected_urls:
        decision = classify_source_url(url)
        assert not decision.accepted, decision
        assert is_gallery_chrome(url), decision


def test_extractor_rejects_nested_container_chrome_that_matches_detail_shape():
    rejected_urls = [
        "https://land-book.com/websites/search",
        "https://land-book.com/websites/latest",
        "https://godly.website/websites/categories",
        "https://mobbin.com/apps/categories",
    ]

    for url in rejected_urls:
        decision = classify_source_url(url)
        assert not decision.accepted, decision
        assert "chrome" in decision.reason


def test_candidate_selection_preserves_order_dedupes_and_filters_chrome():
    candidates = [
        ExtractionCandidate("https://land-book.com/websites/sunday-supply"),
        ExtractionCandidate("https://land-book.com/websites"),
        ExtractionCandidate("https://fontsinuse.com/uses/20234/aesop-logo-website-and-packaging"),
        ExtractionCandidate("https://land-book.com/websites/sunday-supply"),
        ExtractionCandidate("https://mobbin.com/browse"),
        ExtractionCandidate("https://mobbin.com/apps/airbnb-ios/screens"),
    ]

    selected = select_extractable_candidates(candidates)

    assert [candidate.url for candidate in selected] == [
        "https://land-book.com/websites/sunday-supply",
        "https://fontsinuse.com/uses/20234/aesop-logo-website-and-packaging",
        "https://mobbin.com/apps/airbnb-ios/screens",
    ]


def test_source_artifact_extraction_accepts_actual_detail_fixture():
    url = "https://land-book.com/websites/sunday-supply"
    html = """
    <html>
      <head>
        <title>Sunday Supply - Land-book</title>
        <meta property="og:title" content="Sunday Supply Website" />
        <meta property="og:image" content="https://cdn.example.com/sunday-supply.jpg" />
        <meta name="description" content="A showcased commerce site with large product photography, confident type hierarchy, and a warm editorial landing page." />
      </head>
      <body>
        <h1>Sunday Supply Website</h1>
        <p>The page uses a large product hero, responsive editorial frames, and specific retail storytelling.</p>
      </body>
    </html>
    """

    artifact = extract_showcased_artifact(url, html)

    assert artifact is not None
    assert artifact.source_slug == "land-book"
    assert artifact.artifact_kind == "website showcase"
    assert artifact.title == "Sunday Supply Website"
    assert "large product photography" in artifact.summary
    assert artifact.assets == ("https://cdn.example.com/sunday-supply.jpg",)
    assert "actual-work-artifact" in artifact.tags


def test_source_artifact_extraction_rejects_container_chrome_even_with_html():
    url = "https://land-book.com/websites"
    html = "<html><head><title>All Websites</title></head><body><h1>All Websites</h1><p>Browse our website gallery.</p></body></html>"

    assert extract_showcased_artifact(url, html) is None
    assert extract_source_artifacts([url], {url: html}) == ()


def test_source_packs_are_deterministic_local_lenses():
    brief = "Joyful retro-futurist product page for a DTC scent kit with strong typography and checkout flow."

    first_lenses = recommend_source_lenses(brief)
    second_lenses = recommend_source_lenses(brief)
    first_packs = recommend_source_packs(brief)
    second_packs = recommend_source_packs(brief)

    assert first_lenses == second_lenses
    assert first_packs == second_packs
    assert first_lenses[0].slug == "commerce-conversion"
    assert first_packs[0].slug == "web-commerce-pack"


def test_source_plan_resolves_deduped_sources_and_pack_coverage():
    plan = build_source_plan("Packaging, brand identity, and mobile onboarding for a nostalgic snack app.")
    source_slugs = [source.slug for source in plan.sources]
    pack_slugs = {pack.slug for pack in list_source_packs()}
    covered_source_slugs = {
        source_slug
        for pack in list_source_packs()
        for source_slug in pack.source_slugs
    }

    assert len(source_slugs) == len(set(source_slugs))
    assert "brand-system-pack" in {pack.slug for pack in plan.packs}
    assert "the-dieline" in source_slugs
    assert "mobbin" in source_slugs
    assert pack_slugs == {
        "brand-system-pack",
        "image-culture-pack",
        "web-commerce-pack",
        "launch-dossier-pack",
    }
    assert covered_source_slugs == {source.slug for source in list_sources()}
