# Third-party browser asset notices

This service vendors the browser dependencies below for its optional offline browser interface.
They retain their existing versions and are copied byte-for-byte from official pinned distributions.
Original license texts are included beside each component under static/vendor and must accompany
those assets in the Windows 10/11 x64 USB portable release.

| Component | Version | License | Original license file |
| --- | --- | --- | --- |
| bootstrap | 5.3.0 | MIT | [static/vendor/bootstrap/5.3.0/LICENSE](static/vendor/bootstrap/5.3.0/LICENSE) |
| jquery | 3.7.1 | MIT | [static/vendor/jquery/3.7.1/LICENSE.txt](static/vendor/jquery/3.7.1/LICENSE.txt) |
| datatables.net | 1.13.8 | MIT | [static/vendor/datatables.net/1.13.8/License.txt](static/vendor/datatables.net/1.13.8/License.txt) |
| datatables.net-bs5 | 1.13.8 | MIT | [static/vendor/datatables.net-bs5/1.13.8/License.txt](static/vendor/datatables.net-bs5/1.13.8/License.txt) |
| datatables.net-responsive | 2.5.0 | MIT | [static/vendor/datatables.net-responsive/2.5.0/License.txt](static/vendor/datatables.net-responsive/2.5.0/License.txt) |
| datatables.net-responsive-bs5 | 2.5.0 | MIT | [static/vendor/datatables.net-responsive-bs5/2.5.0/License.txt](static/vendor/datatables.net-responsive-bs5/2.5.0/License.txt) |
| @popperjs/core | 2.11.7 | MIT | [static/vendor/popperjs/core/2.11.7/LICENSE.md](static/vendor/popperjs/core/2.11.7/LICENSE.md) |
| datatables-plugins-i18n | 1.13.8 | MIT | [static/vendor/datatables-plugins/1.13.8/License.txt](static/vendor/datatables-plugins/1.13.8/License.txt) |

Bootstrap's JavaScript bundle contains Popper. Its MIT license is included separately even though
the browser loads no separate Popper script. The Bootstrap source maps are bundled unchanged and
contain the corresponding original source content.

The Chinese translation and its license come from the original official DataTables plug-ins
1.13.8 distribution. NPM does not publish that plug-ins version; the translation has therefore
not been substituted with the different 1.13.6 package file.

The canonical provenance and integrity record is [packaging/vendor-assets.json](packaging/vendor-assets.json).
It records exact distribution URLs, package versions, NPM archive SHA256 and SHA512 integrity,
and the SHA256 and byte length of every bundled asset and original license.

Official distribution references:

- [Bootstrap](https://getbootstrap.com/docs/5.3/getting-started/download/)
- [jQuery](https://jquery.com/download/)
- [DataTables NPM packages](https://datatables.net/download/npm)
- [DataTables pinned Chinese translation](https://cdn.datatables.net/plug-ins/1.13.8/i18n/zh.json)
- [DataTables pinned plug-ins license](https://cdn.datatables.net/plug-ins/1.13.8/License.txt)
- [Popper](https://popper.js.org/)

Maintainer regeneration, from the project root:

```powershell
powershell.exe -NoProfile -File .\packaging\vendor-assets.ps1
```

Offline integrity verification:

```powershell
powershell.exe -NoProfile -File .\packaging\vendor-assets.ps1 -VerifyOnly
python -B -m unittest -v test_offline_assets
node .\test_dashboard_logic.cjs
```

Only the maintainer regeneration operation needs download access. It uses Windows PowerShell 5.1
and .NET directly, with no npm install, Node.js, Python, archive utility, package scripts, or browser.
It verifies complete downloads before publishing, writes replacement files atomically, and skips
downloads and writes when local hashes already match. Never hand-edit the vendored minified files.
Python and Node.js in the commands above are developer test tools, not portable runtime dependencies.
The portable service does not run the regeneration or test commands and the browser remains optional.
