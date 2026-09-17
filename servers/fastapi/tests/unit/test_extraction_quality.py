from models.extraction_quality import (
    VisualExtractability,
    VisualQualityFlag,
    group_quality_flags,
)


def _flag(source_file, status, location="Slide 1"):
    return VisualQualityFlag(
        source_file=source_file,
        location=location,
        visual_kind="chart",
        status=status,
        detail="detail",
        recommendation="recommendation",
    )


def test_groups_flags_by_source_file_and_status():
    flags = [
        _flag("a.pdf", VisualExtractability.IMAGE_ONLY, "Page 1"),
        _flag("a.pdf", VisualExtractability.IMAGE_ONLY, "Page 2"),
        _flag("a.pdf", VisualExtractability.PARTIAL, "Page 3"),
        _flag("b.pptx", VisualExtractability.IMAGE_ONLY, "Slide 1"),
    ]

    groups = group_quality_flags(flags)

    assert len(groups) == 3
    group_by_key = {group.group_key: group for group in groups}
    assert group_by_key["a.pdf::image_only"].items[0].location == "Page 1"
    assert len(group_by_key["a.pdf::image_only"].items) == 2
    assert len(group_by_key["a.pdf::partial"].items) == 1
    assert len(group_by_key["b.pptx::image_only"].items) == 1


def test_image_only_groups_sort_before_partial_groups_of_equal_size():
    flags = [
        _flag("a.pdf", VisualExtractability.PARTIAL),
        _flag("b.pptx", VisualExtractability.IMAGE_ONLY),
    ]

    groups = group_quality_flags(flags)

    assert groups[0].status == VisualExtractability.IMAGE_ONLY
    assert groups[1].status == VisualExtractability.PARTIAL


def test_larger_groups_sort_before_smaller_groups_of_the_same_status():
    flags = [
        _flag("small.pdf", VisualExtractability.IMAGE_ONLY),
        _flag("big.pdf", VisualExtractability.IMAGE_ONLY),
        _flag("big.pdf", VisualExtractability.IMAGE_ONLY),
    ]

    groups = group_quality_flags(flags)

    assert groups[0].source_file == "big.pdf"
    assert groups[0].summary.startswith("2 visuals")
    assert groups[1].source_file == "small.pdf"
    assert groups[1].summary.startswith("1 visual ")


def test_acknowledged_keys_mark_matching_groups_acknowledged():
    flags = [_flag("a.pdf", VisualExtractability.IMAGE_ONLY)]

    groups = group_quality_flags(flags, acknowledged_keys=["a.pdf::image_only"])

    assert groups[0].acknowledged is True


def test_unacknowledged_group_defaults_to_false():
    flags = [_flag("a.pdf", VisualExtractability.IMAGE_ONLY)]

    groups = group_quality_flags(flags, acknowledged_keys=None)

    assert groups[0].acknowledged is False


def test_no_flags_produces_no_groups():
    assert group_quality_flags([]) == []


def test_partial_summary_copy_is_distinct_from_image_only_copy():
    image_only_summary = group_quality_flags(
        [_flag("a.pdf", VisualExtractability.IMAGE_ONLY)]
    )[0].summary
    partial_summary = group_quality_flags(
        [_flag("a.pdf", VisualExtractability.PARTIAL)]
    )[0].summary

    assert "no extractable data" in image_only_summary
    assert "partially recovered" in partial_summary
