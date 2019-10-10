import logging
import sys

import pytest
from mock import Mock, patch
from pip._vendor.packaging.specifiers import SpecifierSet
from pkg_resources import parse_version

import pip._internal.pep425tags
import pip._internal.wheel
from pip._internal.exceptions import (
    BestVersionAlreadyInstalled,
    DistributionNotFound,
)
from pip._internal.index import (
    CandidateEvaluator,
    InstallationCandidate,
    Link,
    LinkEvaluator,
)
from pip._internal.models.target_python import TargetPython
from pip._internal.req.constructors import install_req_from_line
from tests.lib import make_test_finder


def make_no_network_finder(
    find_links,
    allow_all_prereleases=False,  # type: bool
):
    """
    Create and return a PackageFinder instance for test purposes that
    doesn't make any network requests when _get_pages() is called.
    """
    finder = make_test_finder(
        find_links=find_links,
        allow_all_prereleases=allow_all_prereleases,
    )
    # Replace the PackageFinder._link_collector's _get_pages() with a no-op.
    link_collector = finder._link_collector
    link_collector._get_pages = lambda locations: []

    return finder


def test_no_mpkg(data):
    """Finder skips zipfiles with "macosx10" in the name."""
    finder = make_test_finder(find_links=[data.find_links])
    req = install_req_from_line("pkgwithmpkg")
    found = finder.find_requirement(req, False)

    assert found.url.endswith("pkgwithmpkg-1.0.tar.gz"), found


def test_no_partial_name_match(data):
    """Finder requires the full project name to match, not just beginning."""
    finder = make_test_finder(find_links=[data.find_links])
    req = install_req_from_line("gmpy")
    found = finder.find_requirement(req, False)

    assert found.url.endswith("gmpy-1.15.tar.gz"), found


def test_tilde():
    """Finder can accept a path with ~ in it and will normalize it."""
    with patch('pip._internal.collector.os.path.exists', return_value=True):
        finder = make_test_finder(find_links=['~/python-pkgs'])
    req = install_req_from_line("gmpy")
    with pytest.raises(DistributionNotFound):
        finder.find_requirement(req, False)


def test_duplicates_sort_ok(data):
    """Finder successfully finds one of a set of duplicates in different
    locations"""
    finder = make_test_finder(find_links=[data.find_links, data.find_links2])
    req = install_req_from_line("duplicate")
    found = finder.find_requirement(req, False)

    assert found.url.endswith("duplicate-1.0.tar.gz"), found


def test_finder_detects_latest_find_links(data):
    """Test PackageFinder detects latest using find-links"""
    req = install_req_from_line('simple', None)
    finder = make_test_finder(find_links=[data.find_links])
    link = finder.find_requirement(req, False)
    assert link.url.endswith("simple-3.0.tar.gz")


def test_incorrect_case_file_index(data):
    """Test PackageFinder detects latest using wrong case"""
    req = install_req_from_line('dinner', None)
    finder = make_test_finder(index_urls=[data.find_links3])
    link = finder.find_requirement(req, False)
    assert link.url.endswith("Dinner-2.0.tar.gz")


@pytest.mark.network
def test_finder_detects_latest_already_satisfied_find_links(data):
    """Test PackageFinder detects latest already satisfied using find-links"""
    req = install_req_from_line('simple', None)
    # the latest simple in local pkgs is 3.0
    latest_version = "3.0"
    satisfied_by = Mock(
        location="/path",
        parsed_version=parse_version(latest_version),
        version=latest_version
    )
    req.satisfied_by = satisfied_by
    finder = make_test_finder(find_links=[data.find_links])

    with pytest.raises(BestVersionAlreadyInstalled):
        finder.find_requirement(req, True)


@pytest.mark.network
def test_finder_detects_latest_already_satisfied_pypi_links():
    """Test PackageFinder detects latest already satisfied using pypi links"""
    req = install_req_from_line('initools', None)
    # the latest initools on PyPI is 0.3.1
    latest_version = "0.3.1"
    satisfied_by = Mock(
        location="/path",
        parsed_version=parse_version(latest_version),
        version=latest_version,
    )
    req.satisfied_by = satisfied_by
    finder = make_test_finder(index_urls=["http://pypi.org/simple/"])

    with pytest.raises(BestVersionAlreadyInstalled):
        finder.find_requirement(req, True)


class TestWheel:

    def test_skip_invalid_wheel_link(self, caplog, data):
        """
        Test if PackageFinder skips invalid wheel filenames
        """
        caplog.set_level(logging.DEBUG)

        req = install_req_from_line("invalid")
        # data.find_links contains "invalid.whl", which is an invalid wheel
        finder = make_test_finder(find_links=[data.find_links])
        with pytest.raises(DistributionNotFound):
            finder.find_requirement(req, True)

        assert 'Skipping link: invalid wheel filename:' in caplog.text

    def test_not_find_wheel_not_supported(self, data, monkeypatch):
        """
        Test not finding an unsupported wheel.
        """
        req = install_req_from_line("simple.dist")
        target_python = TargetPython()
        # Make sure no tags will match.
        target_python._valid_tags = []
        finder = make_test_finder(
            find_links=[data.find_links],
            target_python=target_python,
        )

        with pytest.raises(DistributionNotFound):
            finder.find_requirement(req, True)

    def test_find_wheel_supported(self, data, monkeypatch):
        """
        Test finding supported wheel.
        """
        monkeypatch.setattr(
            pip._internal.pep425tags,
            "get_supported",
            lambda **kw: [('py2', 'none', 'any')],
        )

        req = install_req_from_line("simple.dist")
        finder = make_test_finder(find_links=[data.find_links])
        found = finder.find_requirement(req, True)
        assert (
            found.url.endswith("simple.dist-0.1-py2.py3-none-any.whl")
        ), found

    def test_wheel_over_sdist_priority(self, data):
        """
        Test wheels have priority over sdists.
        `test_link_sorting` also covers this at lower level
        """
        req = install_req_from_line("priority")
        finder = make_test_finder(find_links=[data.find_links])
        found = finder.find_requirement(req, True)
        assert found.url.endswith("priority-1.0-py2.py3-none-any.whl"), found

    def test_existing_over_wheel_priority(self, data):
        """
        Test existing install has priority over wheels.
        `test_link_sorting` also covers this at a lower level
        """
        req = install_req_from_line('priority', None)
        latest_version = "1.0"
        satisfied_by = Mock(
            location="/path",
            parsed_version=parse_version(latest_version),
            version=latest_version,
        )
        req.satisfied_by = satisfied_by
        finder = make_test_finder(find_links=[data.find_links])

        with pytest.raises(BestVersionAlreadyInstalled):
            finder.find_requirement(req, True)

    def test_link_sorting(self):
        """
        Test link sorting
        """
        links = [
            InstallationCandidate("simple", "2.0", Link('simple-2.0.tar.gz')),
            InstallationCandidate(
                "simple",
                "1.0",
                Link('simple-1.0-pyT-none-TEST.whl'),
            ),
            InstallationCandidate(
                "simple",
                '1.0',
                Link('simple-1.0-pyT-TEST-any.whl'),
            ),
            InstallationCandidate(
                "simple",
                '1.0',
                Link('simple-1.0-pyT-none-any.whl'),
            ),
            InstallationCandidate(
                "simple",
                '1.0',
                Link('simple-1.0.tar.gz'),
            ),
        ]
        valid_tags = [
            ('pyT', 'none', 'TEST'),
            ('pyT', 'TEST', 'any'),
            ('pyT', 'none', 'any'),
        ]
        specifier = SpecifierSet()
        evaluator = CandidateEvaluator(
            'my-project', supported_tags=valid_tags, specifier=specifier,
        )
        sort_key = evaluator._sort_key
        results = sorted(links, key=sort_key, reverse=True)
        results2 = sorted(reversed(links), key=sort_key, reverse=True)

        assert links == results == results2, results2

    def test_link_sorting_wheels_with_build_tags(self):
        """Verify build tags affect sorting."""
        links = [
            InstallationCandidate(
                "simplewheel",
                "2.0",
                Link("simplewheel-2.0-1-py2.py3-none-any.whl"),
            ),
            InstallationCandidate(
                "simplewheel",
                "2.0",
                Link("simplewheel-2.0-py2.py3-none-any.whl"),
            ),
            InstallationCandidate(
                "simplewheel",
                "1.0",
                Link("simplewheel-1.0-py2.py3-none-any.whl"),
            ),
        ]
        candidate_evaluator = CandidateEvaluator.create('my-project')
        sort_key = candidate_evaluator._sort_key
        results = sorted(links, key=sort_key, reverse=True)
        results2 = sorted(reversed(links), key=sort_key, reverse=True)
        assert links == results == results2, results2


def test_finder_priority_file_over_page(data):
    """Test PackageFinder prefers file links over equivalent page links"""
    req = install_req_from_line('gmpy==1.15', None)
    finder = make_test_finder(
        find_links=[data.find_links],
        index_urls=["http://pypi.org/simple/"],
    )
    all_versions = finder.find_all_candidates(req.name)
    # 1 file InstallationCandidate followed by all https ones
    assert all_versions[0].link.scheme == 'file'
    assert all(version.link.scheme == 'https'
               for version in all_versions[1:]), all_versions

    link = finder.find_requirement(req, False)
    assert link.url.startswith("file://")


def test_finder_priority_nonegg_over_eggfragments():
    """Test PackageFinder prefers non-egg links over "#egg=" links"""
    req = install_req_from_line('bar==1.0', None)
    links = ['http://foo/bar.py#egg=bar-1.0', 'http://foo/bar-1.0.tar.gz']

    finder = make_no_network_finder(links)
    all_versions = finder.find_all_candidates(req.name)
    assert all_versions[0].link.url.endswith('tar.gz')
    assert all_versions[1].link.url.endswith('#egg=bar-1.0')

    link = finder.find_requirement(req, False)

    assert link.url.endswith('tar.gz')

    links.reverse()

    finder = make_no_network_finder(links)
    all_versions = finder.find_all_candidates(req.name)
    assert all_versions[0].link.url.endswith('tar.gz')
    assert all_versions[1].link.url.endswith('#egg=bar-1.0')
    link = finder.find_requirement(req, False)

    assert link.url.endswith('tar.gz')


def test_finder_only_installs_stable_releases(data):
    """
    Test PackageFinder only accepts stable versioned releases by default.
    """

    req = install_req_from_line("bar", None)

    # using a local index (that has pre & dev releases)
    finder = make_test_finder(index_urls=[data.index_url("pre")])
    link = finder.find_requirement(req, False)
    assert link.url.endswith("bar-1.0.tar.gz"), link.url

    # using find-links
    links = ["https://foo/bar-1.0.tar.gz", "https://foo/bar-2.0b1.tar.gz"]

    finder = make_no_network_finder(links)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-1.0.tar.gz"

    links.reverse()

    finder = make_no_network_finder(links)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-1.0.tar.gz"


def test_finder_only_installs_data_require(data):
    """
    Test whether the PackageFinder understand data-python-requires

    This can optionally be exposed by a simple-repository to tell which
    distribution are compatible with which version of Python by adding a
    data-python-require to the anchor links.

    See pep 503 for more information.
    """

    # using a local index (that has pre & dev releases)
    finder = make_test_finder(index_urls=[data.index_url("datarequire")])
    links = finder.find_all_candidates("fakepackage")

    expected = ['1.0.0', '9.9.9']
    if (2, 7) < sys.version_info < (3,):
        expected.append('2.7.0')
    elif sys.version_info > (3, 3):
        expected.append('3.3.0')

    assert {str(v.version) for v in links} == set(expected)


def test_finder_installs_pre_releases(data):
    """
    Test PackageFinder finds pre-releases if asked to.
    """

    req = install_req_from_line("bar", None)

    # using a local index (that has pre & dev releases)
    finder = make_test_finder(
        index_urls=[data.index_url("pre")],
        allow_all_prereleases=True,
    )
    link = finder.find_requirement(req, False)
    assert link.url.endswith("bar-2.0b1.tar.gz"), link.url

    # using find-links
    links = ["https://foo/bar-1.0.tar.gz", "https://foo/bar-2.0b1.tar.gz"]

    finder = make_no_network_finder(links, allow_all_prereleases=True)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-2.0b1.tar.gz"

    links.reverse()

    finder = make_no_network_finder(links, allow_all_prereleases=True)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-2.0b1.tar.gz"


def test_finder_installs_dev_releases(data):
    """
    Test PackageFinder finds dev releases if asked to.
    """

    req = install_req_from_line("bar", None)

    # using a local index (that has dev releases)
    finder = make_test_finder(
        index_urls=[data.index_url("dev")],
        allow_all_prereleases=True,
    )
    link = finder.find_requirement(req, False)
    assert link.url.endswith("bar-2.0.dev1.tar.gz"), link.url


def test_finder_installs_pre_releases_with_version_spec():
    """
    Test PackageFinder only accepts stable versioned releases by default.
    """
    req = install_req_from_line("bar>=0.0.dev0", None)
    links = ["https://foo/bar-1.0.tar.gz", "https://foo/bar-2.0b1.tar.gz"]

    finder = make_no_network_finder(links)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-2.0b1.tar.gz"

    links.reverse()

    finder = make_no_network_finder(links)
    link = finder.find_requirement(req, False)
    assert link.url == "https://foo/bar-2.0b1.tar.gz"


class TestLinkEvaluator(object):

    def make_test_link_evaluator(self, formats):
        target_python = TargetPython()
        return LinkEvaluator(
            project_name='pytest',
            canonical_name='pytest',
            formats=formats,
            target_python=target_python,
            allow_yanked=True,
        )

    @pytest.mark.parametrize('url, expected_version', [
        ('http:/yo/pytest-1.0.tar.gz', '1.0'),
        ('http:/yo/pytest-1.0-py2.py3-none-any.whl', '1.0'),
    ])
    def test_evaluate_link__match(self, url, expected_version):
        """Test that 'pytest' archives match for 'pytest'"""
        link = Link(url)
        evaluator = self.make_test_link_evaluator(formats=['source', 'binary'])
        actual = evaluator.evaluate_link(link)
        assert actual == (True, expected_version)

    @pytest.mark.parametrize('url, expected_msg', [
        # TODO: Uncomment this test case when #1217 is fixed.
        # 'http:/yo/pytest-xdist-1.0.tar.gz',
        ('http:/yo/pytest2-1.0.tar.gz',
         'Missing project version for pytest'),
        ('http:/yo/pytest_xdist-1.0-py2.py3-none-any.whl',
         'wrong project name (not pytest)'),
    ])
    def test_evaluate_link__substring_fails(self, url, expected_msg):
        """Test that 'pytest<something> archives won't match for 'pytest'."""
        link = Link(url)
        evaluator = self.make_test_link_evaluator(formats=['source', 'binary'])
        actual = evaluator.evaluate_link(link)
        assert actual == (False, expected_msg)


def test_find_all_candidates_nothing():
    """Find nothing without anything"""
    finder = make_test_finder()
    assert not finder.find_all_candidates('pip')


def test_find_all_candidates_find_links(data):
    finder = make_test_finder(find_links=[data.find_links])
    versions = finder.find_all_candidates('simple')
    assert [str(v.version) for v in versions] == ['3.0', '2.0', '1.0']


def test_find_all_candidates_index(data):
    finder = make_test_finder(index_urls=[data.index_url('simple')])
    versions = finder.find_all_candidates('simple')
    assert [str(v.version) for v in versions] == ['1.0']


def test_find_all_candidates_find_links_and_index(data):
    finder = make_test_finder(
        find_links=[data.find_links],
        index_urls=[data.index_url('simple')],
    )
    versions = finder.find_all_candidates('simple')
    # first the find-links versions then the page versions
    assert [str(v.version) for v in versions] == ['3.0', '2.0', '1.0', '1.0']
