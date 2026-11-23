# Versioned releases

There is one source tree and two distribution outputs.

1. Develop and test on branches. Merge verified changes into `main`.
2. Update `RUNNING_VERSION`, `fusion360-isogrid.manifest` and changelog together.
3. Validate using `python -m unittest discover -s tests` and `python tools/build_release.py --version X.Y.Z`.
4. The push to `main` triggers the release workflow. It reruns tests, builds both distributions and validates the archives.
5. If `vX.Y.Z` has no existing GitHub Release, the workflow tags the verified `main` commit and publishes the GitHub ZIP, Marketplace ZIP, icon and SHA256SUMS. Subsequent commits with the same version do not republish.
6. The GitHub add-in queries `/releases/latest` and only offers updates when that stable release has its expected `fusion360-isogrid-vX.Y.Z-github.zip` asset.
7. Submit the same version's Marketplace ZIP in Autodesk Publisher Center. Autodesk builds the platform-specific installers.

GitHub's source-code ZIP is **not** an updater installation archive. The updater only installs the curated GitHub ZIP asset. Marketplace ZIPs omit `update_checker.py`, disable updater initialization and hide updater controls. Both packages include GPLv3 and the privacy policy.
