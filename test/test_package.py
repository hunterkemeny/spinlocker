# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""spinlocker package test"""

import unittest


class TestPackage(unittest.TestCase):
    """This contains tests that the auto generated package"""

    def test_package_import(self):
        """Test package can be imported successfully"""
        try:
            # pylint: disable = unused-import
            import spinlocker

            version = custom_experiment.__version__
            self.assertTrue(version)

        # pylint: disable = broad-except
        except Exception as ex:
            self.fail(f"Failed to import package. Import raised exception {ex}")
