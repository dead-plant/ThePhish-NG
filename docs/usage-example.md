# Usage Example

## Table of Contents

* [Forwarding an email to ThePhish-NG](#forwarding-an-email-to-thephish-ng)
  * [Thunderbird](#thunderbird)
  * [Outlook](#outlook)
* [Analysis Example](#analysis-example)
  * [Start of Analysis](#start-of-analysis)
  * [Case Creation](#case-creation)
  * [Analyzing the Observables](#analyzing-the-observables)
  * [Verdict](#verdict)
  * [Result Email](#result-email)
* [Manual Review](#manual-review)
  * [Download EML](#download-eml)
  * [Set IoC Flag](#set-ioc-flag)
  * [Close the Case](#close-the-case)
  * [Manually Send Result Email](#manually-send-result-email)
  * [Export the Case to MISP](#export-the-case-to-misp)

## Forwarding an email to ThePhish-NG

For ThePhish-NG to be able to analyze an email, it has to be forwarded to the inbox of ThePhish-NG as an EML attachment.

This can be done in most email clients. I'll provide examples for the Outlook and Thunderbird clients:

### Thunderbird

To forward the email as an attachment you have to right-click on the email and select `As Attachment` under the `Forward and Redirect` section.

<img src="img/usage-example/forward-thunderbird.png" width="800">

### Outlook

In Outlook you have to click on the three dots on the top right of the email and then click on `Forward as Attachment`.

<img src="img/usage-example/forward-outlook.png" width="800">

## Analysis Example

### Start of Analysis

First, the analyst opens the web UI and clicks on the `List Emails` button to display all valid emails.

<img src="img/usage-example/list-emails.png" width="800">

When the analyst clicks on the `Analyze` button next to the selected email,
the application will create the analysis and redirect the analyst to the analysis page.

<img src="img/usage-example/start-of-analysis.png" width="800">

### Case Creation

At the beginning of an analysis, ThePhish-NG will automatically retrieve the email, filter the observables, create a case in TheHive and add the observables to the created case. After the case creation is completed, it will notify the submitter that the analysis has started. The notification behavior can also be configured in the application config.

This behavior can also be observed when opening the case in TheHive:

* Case:

  <img src="img/usage-example/thehive-case.png" width="800">

* Added observables:

  <img src="img/usage-example/thehive-observables.png" width="800">

* Tasks created by ThePhish-NG:

  <img src="img/usage-example/thehive-tasks.png" width="800">

### Analyzing the Observables

After the user has been notified, ThePhish-NG will build a list of Cortex jobs containing Analyzer jobs for all the observables.

Next, it will start the jobs, poll their statuses until they finish, fail or time out and then read the results:

<img src="img/usage-example/thephish-log-analyzers.png" width="800">

If you want, you can look at the Cortex job history to see the current status of the analyzers yourself:

<img src="img/usage-example/cortex-job-history.png" width="800">

### Verdict

ThePhish-NG calculates a verdict based on the analyzer results and your configured malicious observable threshold. If the number of malicious observables is greater than or equal to the configured threshold, the verdict is malicious. If at least one observable is malicious or suspicious and the threshold isn't reached, it is suspicious; otherwise, it is safe.

Depending on your configuration, the case in TheHive can automatically be closed and, if malicious, exported to MISP. By default, automatic case closing for safe and malicious verdicts and automatic MISP export are enabled. For suspicious verdicts, the default configuration will leave the case open for [Manual Review](#manual-review).

* Verdict displayed in ThePhish-NG:

  <img src="img/usage-example/thephish-verdict-malicious.png" width="800">

* Closed TheHive case:

  <img src="img/usage-example/thehive-closed-case.png" width="800">

* MISP event:

  <img src="img/usage-example/misp-event.png" width="800">

ThePhish-NG marks all malicious observables as IoCs, so these observables get linked to the MISP event:

<img src="img/usage-example/misp-event-observables.png" width="800">

### Result Email

Depending on your configuration and verdict, you might get an automated response email.

This email can optionally contain a link to the ThePhish-NG analysis page, a summary and the full log of the analysis:

<img src="img/usage-example/result-email.png" width="800">

## Manual Review

If the verdict is suspicious, or if you have configured your instance to leave TheHive cases open, the analyst has to look at the TheHive case, decide whether it's malicious, close the case and send the notification manually. Optionally, the analyst can also set the IoC flag on observables and export the case to MISP.

To do this, the analyst can look at the log produced by ThePhish-NG or directly at the observables/jobs in TheHive or Cortex. If the analyst decides to review it manually, he can download the suspicious EML from TheHive.

### Download EML

First, find the EML in the Observables list of the case in TheHive. Most of the time this will have the name `email.eml`.

Then just click on the three dots and click download.

<img src="img/usage-example/thehive-download-eml.png" width="800">

### Set IoC Flag

If you want to set the IoC flag for an observable, just click on its name. Once you're in the observable details, set/unset the flag and click save:

<img src="img/usage-example/thehive-mark-observable-ioc.png" width="800">

### Close the Case

Once you have decided on your verdict, you should close the case. You can do this by clicking on the close button in the top-right of your screen and selecting a verdict:

<img src="img/usage-example/thehive-close-case-button.png" width="800">

In the popup, you can select your verdict, type a summary and click confirm to close the case.

<img src="img/usage-example/thehive-close-case-popup.png" width="800">

### Manually Send Result Email

After setting the verdict, you might want to send or re-send the result email to the submitter.

To do this, open the `ThePhish result` task in TheHive. The description of that task is the input of the Mailer responder.

The first line tells the responder who to send that email to and, if using the custom PhishMailer responder, which subject to use.

ThePhish-NG should have already prefilled the log and the header for the best available responder.

Note: The instructions for the standard Mailer and PhishMailer responders are not compatible with each other. ThePhish-NG should have already prefilled the correct header. If your Cortex instance has both, make sure to run the PhishMailer responder, not the Mailer.

<img src="img/usage-example/thehive-result-task-description.png" width="800">

Once you've edited the description, you can run the responder by clicking on the three dots in the top-right, clicking responder and then launching it.

<img src="img/usage-example/thehive-launch-responder-popup.png" width="800">

### Export the Case to MISP

If you decide the email is malicious, you might want to export the case to MISP.

You can do that by clicking on the export case button next to the close case button. In the popup, you have to select your MISP instance and click export.

<img src="img/usage-example/thehive-case-export-popup.png" width="800">
