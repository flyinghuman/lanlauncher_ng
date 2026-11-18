# Bundled Python sources

- `ouisync/session`: upstream Ouisync session binding, version 0.10.1, from
  `equalitie/ouisync` commit `fd5bc904527aec6eeeb3cd7e1b96c099e939546b`.
  Licensed under MPL-2.0; see `vendor/licenses/ouisync/MPL-2.0.txt`.
- The matching Ouisync CLI 0.10.1 is built from the same commit for Windows
  and Linux without the optional VFS mount feature. Its dependency inventory
  and license texts are in `vendor/licenses/ouisync/THIRD-PARTY-NOTICES.txt`.
  The Linux binary was built on Debian Bullseye and requires glibc 2.30 or newer.
- `msgpack`: pure-Python implementation files from msgpack 1.1.2. Its C
  extension is omitted so the same bundle works on Windows and Linux; the
  upstream package automatically selects its fallback implementation.
  Licensed under Apache-2.0; see `vendor/licenses/msgpack/LICENSE.txt`.

The Ouisync session protocol uses MessagePack, which the Python standard
library does not implement. These sources are bundled so normal LLNG runtime
does not need Internet access or package installation.
