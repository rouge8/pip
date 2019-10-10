import os
import re

import pytest

from pip import __version__
from pip._internal.commands.show import search_packages_info


def test_basic_show(script):
    """
    Test end to end test for show command.
    """
    result = script.pip('show', 'pip')
    lines = result.stdout.splitlines()
    assert len(lines) == 10
    assert 'Name: pip' in lines
    assert 'Version: %s' % __version__ in lines
    assert any(line.startswith('Location: ') for line in lines)
    assert 'Requires: ' in lines


def test_show_with_files_not_found(script, data):
    """
    Test for show command with installed files listing enabled and
    installed-files.txt not found.
    """
    editable = data.packages.joinpath('SetupPyUTF8')
    script.pip('install', '-e', editable)
    result = script.pip('show', '-f', 'SetupPyUTF8')
    lines = result.stdout.splitlines()
    assert len(lines) == 12
    assert 'Name: SetupPyUTF8' in lines
    assert 'Version: 0.0.0' in lines
    assert any(line.startswith('Location: ') for line in lines)
    assert 'Requires: ' in lines
    assert 'Files:' in lines
    assert 'Cannot locate installed-files.txt' in lines


def test_show_with_files_from_wheel(script, data):
    """
    Test that a wheel's files can be listed
    """
    wheel_file = data.packages.joinpath('simple.dist-0.1-py2.py3-none-any.whl')
    script.pip('install', '--no-index', wheel_file)
    result = script.pip('show', '-f', 'simple.dist')
    lines = result.stdout.splitlines()
    assert 'Name: simple.dist' in lines
    assert 'Cannot locate installed-files.txt' not in lines[6], lines[6]
    assert re.search(r"Files:\n(  .+\n)+", result.stdout)


@pytest.mark.network
def test_show_with_all_files(script):
    """
    Test listing all files in the show command.
    """
    script.pip('install', 'initools==0.2')
    result = script.pip('show', '--files', 'initools')
    lines = result.stdout.splitlines()
    assert 'Cannot locate installed-files.txt' not in lines[6], lines[6]
    assert re.search(r"Files:\n(  .+\n)+", result.stdout)


def test_missing_argument(script):
    """
    Test show command with no arguments.
    """
    result = script.pip('show', expect_error=True)
    assert 'ERROR: Please provide a package name or names.' in result.stderr


def test_find_package_not_found():
    """
    Test trying to get info about a nonexistent package.
    """
    result = search_packages_info(['abcd3'])
    assert len(list(result)) == 0


def test_report_single_not_found(script):
    """
    Test passing one name and that isn't found.
    """
    # We choose a non-canonicalized name to test that the non-canonical
    # form is logged.
    # Also, the following should report an error as there are no results
    # to print. Consequently, there is no need to pass
    # allow_stderr_warning=True since this is implied by expect_error=True.
    result = script.pip('show', 'Abcd-3', expect_error=True)
    assert 'WARNING: Package(s) not found: Abcd-3' in result.stderr
    assert not result.stdout.splitlines()


def test_report_mixed_not_found(script):
    """
    Test passing a mixture of found and not-found names.
    """
    # We test passing non-canonicalized names.
    result = script.pip(
        'show', 'Abcd3', 'A-B-C', 'pip', allow_stderr_warning=True
    )
    assert 'WARNING: Package(s) not found: A-B-C, Abcd3' in result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 10
    assert 'Name: pip' in lines


def test_search_any_case():
    """
    Search for a package in any case.

    """
    result = list(search_packages_info(['PIP']))
    assert len(result) == 1
    assert result[0]['name'] == 'pip'


def test_more_than_one_package():
    """
    Search for more than one package.

    """
    result = list(search_packages_info(['Pip', 'pytest', 'Virtualenv']))
    assert len(result) == 3


def test_show_verbose_with_classifiers(script):
    """
    Test that classifiers can be listed
    """
    result = script.pip('show', 'pip', '--verbose')
    lines = result.stdout.splitlines()
    assert 'Name: pip' in lines
    assert re.search(r"Classifiers:\n(  .+\n)+", result.stdout)
    assert "Intended Audience :: Developers" in result.stdout


def test_show_verbose_installer(script, data):
    """
    Test that the installer is shown (this currently needs a wheel install)
    """
    wheel_file = data.packages.joinpath('simple.dist-0.1-py2.py3-none-any.whl')
    script.pip('install', '--no-index', wheel_file)
    result = script.pip('show', '--verbose', 'simple.dist')
    lines = result.stdout.splitlines()
    assert 'Name: simple.dist' in lines
    assert 'Installer: pip' in lines


def test_show_verbose(script):
    """
    Test end to end test for verbose show command.
    """
    result = script.pip('show', '--verbose', 'pip')
    lines = result.stdout.splitlines()
    assert any(line.startswith('Metadata-Version: ') for line in lines)
    assert any(line.startswith('Installer: ') for line in lines)
    assert 'Entry-points:' in lines
    assert 'Classifiers:' in lines


def test_all_fields(script):
    """
    Test that all the fields are present
    """
    result = script.pip('show', 'pip')
    lines = result.stdout.splitlines()
    expected = {'Name', 'Version', 'Summary', 'Home-page', 'Author',
                'Author-email', 'License', 'Location', 'Requires',
                'Required-by'}
    actual = {re.sub(':.*$', '', line) for line in lines}
    assert actual == expected


def test_pip_show_is_short(script):
    """
    Test that pip show stays short
    """
    result = script.pip('show', 'pip')
    lines = result.stdout.splitlines()
    assert len(lines) <= 10


def test_pip_show_divider(script, data):
    """
    Expect a divider between packages
    """
    script.pip('install', 'pip-test-package', '--no-index',
               '-f', data.packages)
    result = script.pip('show', 'pip', 'pip-test-package')
    lines = result.stdout.splitlines()
    assert "---" in lines


def test_package_name_is_canonicalized(script, data):
    script.pip('install', 'pip-test-package', '--no-index', '-f',
               data.packages)

    dash_show_result = script.pip('show', 'pip-test-package')
    underscore_upper_show_result = script.pip('show', 'pip-test_Package')

    assert underscore_upper_show_result.returncode == 0
    assert underscore_upper_show_result.stdout == dash_show_result.stdout


def test_show_required_by_packages_basic(script, data):
    """
    Test that installed packages that depend on this package are shown
    """
    editable_path = os.path.join(data.src, 'requires_simple')
    script.pip(
        'install', '--no-index', '-f', data.find_links, editable_path
    )

    result = script.pip('show', 'simple')
    lines = result.stdout.splitlines()

    assert 'Name: simple' in lines
    assert 'Required-by: requires-simple' in lines


def test_show_required_by_packages_capitalized(script, data):
    """
    Test that the installed packages which depend on a package are shown
    where the package has a capital letter
    """
    editable_path = os.path.join(data.src, 'requires_capitalized')
    script.pip(
        'install', '--no-index', '-f', data.find_links, editable_path
    )

    result = script.pip('show', 'simple')
    lines = result.stdout.splitlines()

    assert 'Name: simple' in lines
    assert 'Required-by: Requires-Capitalized' in lines


def test_show_required_by_packages_requiring_capitalized(script, data):
    """
    Test that the installed packages which depend on a package are shown
    where the package has a name with a mix of
    lower and upper case letters
    """
    required_package_path = os.path.join(data.src, 'requires_capitalized')
    script.pip(
        'install', '--no-index', '-f', data.find_links, required_package_path
    )
    editable_path = os.path.join(data.src, 'requires_requires_capitalized')
    script.pip(
        'install', '--no-index', '-f', data.find_links, editable_path
    )

    result = script.pip('show', 'Requires_Capitalized')
    lines = result.stdout.splitlines()
    print(lines)

    assert 'Name: Requires-Capitalized' in lines
    assert 'Required-by: requires-requires-capitalized' in lines
