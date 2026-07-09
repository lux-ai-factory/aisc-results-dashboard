# NOTICE

AISC Collaborative Assessment Dashboard
(part of the AI Assessment Sandbox Configurator)

Copyright (c) 2025-2026
- Interdisciplinary Centre for Security, Reliability and Trust (SnT), University of Luxembourg
- Luxembourg Institute of Science and Technology (LIST)

This software is co-developed and co-maintained by SnT and LIST.

This project is funded under the Luxembourg AI Factory, Horizon Europe grant agreement No. 101234366.

This distribution is provided under the Apache License, Version 2.0.
See the `LICENSE.md` file for the full license text.

## Third-party notices

This product is built on and deploys **Apache Superset**
(https://superset.apache.org/), licensed under the Apache License 2.0.
"Apache Superset", "Superset", "Apache" and the Apache feather logo are
trademarks of the Apache Software Foundation (ASF). This project is not
endorsed by or affiliated with the ASF. No Apache Superset source code is
contained in this repository; the Dockerfile references the official
`apache/superset` image, whose own LICENSE and NOTICE files apply to any
built/redistributed image and must be retained.

Python dependencies installed on top of the base image:

- Authlib (BSD-3-Clause)
- immudb-py (Apache-2.0)
- psycopg2-binary (LGPL-3.0 with exceptions) — note the weak-copyleft license
  when redistributing built images.

## Trademarks and logos

The Luxembourg AI Factory name and logo (`branding/aisc/laif_logo.png`) are
trademarks of their respective owners and are NOT licensed under the Apache
License 2.0. They are included solely for deployment by authorised parties;
remove or replace them when redistributing modified versions.
