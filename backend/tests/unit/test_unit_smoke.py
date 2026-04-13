"""Smoke test — validates unit test fixtures are working."""


def test_valid_pixel_data_size(valid_pixel_data):
    assert len(valid_pixel_data) == 3072


def test_valid_pixel_data_is_red(valid_pixel_data):
    assert valid_pixel_data[:3] == bytes([255, 0, 0])


def test_white_pixel_data_size(white_pixel_data):
    assert len(white_pixel_data) == 3072


def test_random_pixel_data_unique(random_pixel_data):
    assert len(random_pixel_data) == 3072


def test_sample_coords(sample_coords):
    assert (0, 0) in sample_coords
    assert (999, 999) in sample_coords
