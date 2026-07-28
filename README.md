# ThePhish-NG

<div>
  <p align="center">
    <img src="docs/img/pictures-upstream/logo.png" width="800" alt="ThePhish-NG logo"> 
  </p>
</div>

ThePhish-NG is a partial rewrite of the original [ThePhish](https://github.com/emalderson/ThePhish) project with updated features and TheHive 5 support.

It offers a web application built with Python 3 and Flask that automates phishing email analysis using TheHive, Cortex, and MISP.
It handles the full analysis flow from extracting observables, running the applicable analyzers, closing the TheHive case with a verdict and exporting malicious cases to MISP. 

[![OS](https://img.shields.io/badge/OS-Linux-red?style=flat&logo=linux)](#)
[![made-with-python](https://img.shields.io/badge/Made%20with-Python%203.12-1f425f.svg?logo=python)](https://www.python.org/)
[![Maintenance](https://img.shields.io/badge/Maintained-yes-green.svg)](https://github.com/dead-plant/ThePhish-NG)
[![Documentation](https://img.shields.io/badge/Documentation-in%20progress-blue.svg?style=flat)](https://github.com/dead-plant/ThePhish-NG)


## Table of contents

* [Additional Documentation](#additional-documentation)
* [External References](#external-references)
* [Highlighted Features](#highlighted-features)
* [Credits](#credits)
* [License](#license)

## Additional Documentation

* [Usage Example](docs/usage-example.md)
* [Setup Guide](docs/setup.md)
* [Configuration Options](docs/configuration.md)

## External References

* Original ThePhish project: https://github.com/emalderson/ThePhish
* TheHive Documentation: https://docs.strangebee.com/thehive/overview/
* Cortex Documentation: https://docs.strangebee.com/cortex/
* TheHive & Cortex Docker: https://github.com/StrangeBeeCorp/docker
* MISP: https://www.misp-project.org/
* MISP Docker: https://github.com/MISP/misp-docker

## Highlighted Features

* TheHive 5 support
* Background analysis with live logs and configurable retention
* Extracts URLs, domains, IPs, hashes, and other email observables
* Adds attachments and the original EML to TheHive
* Follows redirects and decodes Microsoft 365 Safelinks
* Configurable whitelists, analyzer exclusions, and verdict mappings
* Automatic verdicts and IoC marking
* Exports malicious cases to MISP and keeps suspicious cases open for review
* Start and result emails with a log and link to the web view

## Credits

* [emalderson](https://github.com/emalderson): Creator of the original ThePhish (upstream) project
* [stone](https://github.com/rmfstone): Co-Maintainer of the ThePhish-NG project
* [FabioHofstadler](https://github.com/FabioHofstadler): Logo and Designs

## License

ThePhish-NG is free and open-source software released under the [AGPL-3.0 license](LICENSE).
