# Configuration Options

ThePhish-NG has four config files, each serving a different purpose.
Here you will find an explanation of each file as well as detailed descriptions of all options.

## Table of Contents

* [Versioning](#versioning)
* [Command Line Arguments](#command-line-arguments)
  * [Config Directory](#config-directory)
  * [Bind Address](#bind-address)
  * [Port](#port)
* [Application Config](#application-config)
  * [Webapp](#webapp)
  * [Redis](#redis)
  * [Analysis](#analysis)
  * [IMAP](#imap)
  * [TheHive](#thehive)
  * [Case](#case)
  * [Notifications](#notifications)
* [Whitelist](#whitelist)
* [Analyzer Level Mappings](#analyzer-level-mappings)
  * [Data Type](#data-type)
  * [Level Mapping](#level-mapping)
* [Logging](#logging)

## Versioning

The `app.conf`, `whitelist.json`, and `analyzer_level_mappings.json` files have a `version` attribute.
The version changes when the structure of one of these files changes during a new release.

On every start the application checks whether these versions match the release.
This is done to prevent users from using an incomplete or outdated configuration.

If you get an error saying that your config is outdated, please download the newest template and migrate your settings.

The `version` attribute in `logging.json` is part of the Python logging configuration format and is not tied to ThePhish-NG releases.

## Command Line Arguments

Some options are configured using command line arguments when starting ThePhish-NG.
All arguments are optional.

```console
python run.py --config-dir ./config --bind-addr 127.0.0.1 --port 8080
```

### Config Directory

```console
--config-dir ./config
```

Path to the directory containing the ThePhish-NG configuration files.
The default is the `config` directory next to `run.py`.
Use this option when the configuration files are stored elsewhere.

### Bind Address

```console
--bind-addr 127.0.0.1
```

Network interface the Flask web server binds to. The default is `127.0.0.1`.
You should keep the default in most cases, as it is not recommended to expose the Flask server directly without a reverse proxy.

### Port

```console
--port 8080
```

Port the Flask web server binds to. The default is `8080`.
Change this if the default port is already in use.

## Application Config

**filename:** `app.conf`

**format:** `toml`

**version:** `1`

This is the main configuration file of ThePhish-NG. It is used to configure the behavior and connections of the main application.
It is split into multiple categories, each containing several configuration options.

### Webapp

**Options related to the frontend of the application**

```toml
base_url = "https://thephish.example.com"
```

This is the URL analysts use to access ThePhish-NG.
It is used when linking to ThePhish-NG, for example in the result email that contains a link to the analysis log.
Do not include a trailing slash.

```toml
show_version = true
```

Whether to show the running ThePhish-NG version in the footer and include it in the `/api/health` response.

```toml
thehive_url = "https://link-to-thehive/"
cortex_url = "https://link-to-cortex/"
misp_url = "https://link-to-misp/"
```

These are the target URLs of the links in the navbar on the left.
Ideally, they should point to the base URL of each service.
For example: `https://thehive.example.com/`

### Redis

**Options related to the Redis connections**

```toml
url = "redis://127.0.0.1:6379/0"
```

Redis URL the application uses to store data such as logs, analyses, and results.
This should not be the logical database Celery uses.

```toml
key_prefix = "thephish"
```

Prefix added to the beginning of all Redis keys set by the application. Does not apply to Celery.

```toml
celery_broker_url = "redis://127.0.0.1:6379/1"
celery_result_backend_url = "redis://127.0.0.1:6379/2"
```

Redis URLs for the Celery broker and result backend.
Ideally, these logical databases should not be used by anything else.

### Analysis

**Options related to the analysis**

```toml
retention_days = 7
```

Number of days the analysis data is kept in Redis.
After this time has passed, the analysis status and log will no longer be available in the ThePhish-NG frontend and the link in the result email will stop working.
The associated TheHive case is not affected.

```toml
decode_o365_safelinks = true
```

Whether to decode Microsoft 365 Safe Links and add the decoded URL to the TheHive case as an observable.
Whitelisted URLs are removed before decoding.
Do not whitelist URLs containing `.safelinks.protection.outlook.com` if you want this feature to work.

```toml
follow_url_redirects = true
```

Whether to track URL redirects and add the complete redirect chain to the TheHive case as observables.
Whitelisted URLs will not be followed.

```toml
analyzer_prefix_blacklist = ["UnshortenLink", "MSDefenderOffice365_SafeLinksDecoder_json"]
```

Analyzers whose names start with one of these strings will never be started by ThePhish-NG.
This is useful if your Cortex organization contains analyzers that are incompatible with ThePhish-NG.

```toml
malicious_observable_threshold = 1
```

Number of unique malicious observables required for a malicious verdict.
If at least one observable is malicious but the threshold is not reached, the verdict is suspicious.
Malicious observables are still marked as IoCs regardless of the final verdict.

### IMAP

**Options related to the IMAP connection / Email input**

```toml
host = "imap.gmail.com"
port = 993
```

Host and port of the IMAP server.

```toml
tls_mode = "tls"
```

TLS mode used when connecting to the IMAP server.
Available options are `tls` for implicit TLS, `starttls` for STARTTLS, and `none` for an unencrypted connection.
Make sure your server offers the TLS mode at the configured port.

```toml
tls_verify = true
```

Whether to verify the authenticity of the TLS certificate.
Never disable this when accessing public servers.

```toml
user = "example@gmail.com"
password = "passwort.213"
```

Credentials used to authenticate with the IMAP server.

```toml
folder = "inbox"
```

Mailbox folder from which ThePhish-NG reads emails.

```toml
max_message_size_mb = 25
```

Maximum email size in mebibytes (MiB).
Larger emails are considered invalid, they will not be listed, and will be marked as read in the mailbox.

```toml
email_list_amount = 20
```

Maximum number of valid, unread emails to list.
Invalid emails do not count towards this limit.

### TheHive

**Options related to the connection to TheHive**

```toml
url = "https://thehive.example.com"
```

URL ThePhish-NG uses to access the TheHive API.

```toml
apikey = "generated_api_key"
```

API key of the service user. ThePhish-NG uses this to authenticate to TheHive.

```toml
tls_verify = true
```

Whether to verify the authenticity of the TLS certificate.
Never disable this when accessing public servers.

```toml
cortex_id = "cortex"
misp_id = "MISP"
```

ID of the Cortex and MISP instance set in the connector settings of TheHive.

### Case

**Options related to the TheHive case**

```toml
tlp = 2
pap = 2
```

TLP and PAP values set when a case is created in TheHive.
A Cortex neuron will not run if its maximum supported TLP or PAP is lower than the value set here.

```toml
tags = ["email", "ThePhish"]
```

Tags added to the TheHive case.

```toml
add_analysis_link = true
```

Whether to add a linked element to the TheHive case that points to the ThePhish-NG analysis page.
The link uses the configured `webapp.base_url` and has the type `ThePhish-NG Analysis`.

```toml
export_malicious_to_misp = true
```

Whether to export cases with a malicious verdict to the configured MISP instance after analysis.
This option is independent of automatic case closure.

```toml
auto_close_malicious = true
auto_close_safe = true
auto_close_suspicious = false
```

Whether to automatically close cases after analysis, depending on the verdict.
Malicious cases are closed as `TruePositive`, safe cases as `FalsePositive`, and suspicious cases as `Indeterminate`.
If the option for a verdict is disabled, the case remains open.

### Notifications

**Options related to email notifications**

```toml
send_start = true
send_result_malicious = true
send_result_safe = true
send_result_suspicious = false
```

Whether to send an email when an analysis starts and when it finishes with the corresponding verdict.
If an option is disabled, the responder-formatted email text is still written to the associated TheHive task description, but the responder is not executed.

```toml
include_analysis_link = true
```

Whether to include a link to the analysis page in notification emails.
The link uses the configured `webapp.base_url`.

```toml
include_log = true
```

Whether to include the analysis log in the result email.
The log is only included when `include_verdict` is also enabled.

```toml
include_verdict = true
```

Whether to include the verdict and analyzer summary in the result email.
Disabling this option also disables the analysis log and replaces the result with a generic completion message.

```toml
recipient_override = ""
```

Email address to which all notifications are sent.
If this is empty, notifications are sent to the address that submitted the email for analysis.

## Whitelist

**filename:** `whitelist.json`

**format:** `json`

**version:** `1`

The whitelist is used to ignore specific values during an analysis.
Whitelisted values will not be added to the TheHive case as observables and thus be completely ignored by the analysis.

Consider adding your own domains and IP addresses here to stop them from being analyzed.

The `exactMatching` object contains values that must match exactly.
It supports the `mail`, `ip`, `url`, `domain`, `filename`, `filetype`, and `hash` data types.

The `regexMatching` object contains regular expressions and supports the `mail`, `ip`, `url`, `domain`, and `filename` data types.
Regular expressions match any part of a value unless you anchor them with `^` and `$`.
Backslashes must be escaped in JSON.

Values are converted to lowercase before matching.
Exact values must therefore be lowercase, and regular expressions should be written to match lowercase input.

Example:

```json
{
    "version": 1,
    "exactMatching": {
        "mail": [],
        "ip": ["192.0.2.10"],
        "url": [],
        "domain": ["example.com"],
        "filename": [],
        "filetype": [],
        "hash": []
    },
    "regexMatching": {
        "mail": [],
        "ip": ["10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}"],
        "url": [],
        "domain": ["(^|\\.)example\\.com$"],
        "filename": []
    }
}
```

## Analyzer Level Mappings

**filename:** `analyzer_level_mappings.json`

**format:** `json`

**version:** `1`

This can be used to map the levels returned by specific analyzers to different ones.

Each entry uses the exact analyzer name as its key.
If an analyzer, data type, or reported level is not configured, the original level is returned unchanged.

Example:

```json
{
    "version": 1,
    "MISP_2_1": {
        "dataType": ["url", "ip", "domain", "mail"],
        "levelMapping": {
            "malicious": "malicious",
            "suspicious": "malicious",
            "safe": "safe",
            "info": "info"
        }
    }
}
```

### Data Type

**A list of observable data types**

If the data type of the reported observable is not in the list, the value will not be mapped and will be returned as-is.

You can see the supported data types of each analyzer in Cortex.

Example:

```json
"dataType" : ["url", "ip", "domain", "mail"]
```

### Level Mapping

**Mapping Original -> Mapped**

Here you can map the reported levels to your own. The four valid levels are `info`, `safe`, `suspicious`, and `malicious`.

Example:

```json
"levelMapping" : {
    "malicious" : "malicious",
    "suspicious" : "malicious",
    "safe" : "safe",
    "info" : "info"
}
```

## Logging

**filename:** `logging.json`

**format:** `json`

**version:** `1` (Python logging configuration format)

Configuration of the Python logging system.

This configures the application and service logs, not the analysis logs shown in the web interface or result email.

Most users do not need to change this.
