# GmailTools

***How to train your Gmail***

## Description

GmailTools contains a set of tools to perform (un)usual tasks on Gmail:

* **relabel**: relabel all unlabeled messages in labeled threads\
  \
Gmail's _conversation mode_ always binds all of a thread's message together,
and threads inherit the union of the labels of their messages. New messages
in a thread do not automatically inherit its labels. But this behavior is
undesired: first, searching based on a label may omit messages and confuse
the user (even more so in non-conversation mode!); and second, they will not
appear in their respective mail folder in IMAP. (See references below.)\
  \
The relabel command implements label inheritance in threads. It scans all the
labeled threads and (re)labels all the unlabeled messages in those threads. By
running is periodically (e.g. daily using crontab) you can guarantee that all
the messages in labeled threads are likewise labeled as expected.

More tools will be added as more scratches cry to be itched...

## License

[BSD 3-Clause License](https://opensource.org/licenses/BSD-3-Clause)

## Installation, setup, and usage

**One time setup**

- Download the project \
    `git clone https://github.com/orenl/gmailtools`

- Setup virtualenv \
  (skip if the relevant python libraries from Google are already installed). \
    `virtualenv env` \
    `pip install google-auth-oauthlib install google-api-python-client`

- Obtain Gmail API credentials
  - enable the Gmail API: go to https://console.developers.google.com/apis/library/gmail.googleapis.com.
  - setup OAuth consent screen: go to https://console.developers.google.com/apis/credentials/consent.
  - only need to fill the _"App name"_, _"User support email"_, and _"Email addresses"_.
  - create a new project: go to https://console.developers.google.com/apis/credentials (near search bar).
  - create new credentials: go to https://console.developers.google.com/apis/credentials.
  - select _"Oauth client ID"_, select _"Desktop App"_ and give it a name.
  - download the new credentials, and save as `credentials.json` (and run `chmod 0600 credential.json`).

**Usage**

* To run the tool, simply execute: `gmailtools`.
* If you are using `virtualenv` as described above, you should first go to the
  install directory, and then execute `./gmailtools`.
* If asked to authorize access to GMail, e.g. first time usage, follow the
  instructions in the section below.
* For a help messages with a list of commands and optional arguments, run
  `gmailtools --help`.

**Authorization**

When using the tool for the first time (per gmail account), or if the
`oatuh2token.json` file is missing or corrupt, Google will execute a new
authentication procedure. This typically involves a new browser popup:

  > Choose an account to continue to PROJECT-NAME

  -> choose the desired Gmail account
  > This app isn't verified

  -> Advanced -> Go to PROJECT-NAME
  > Grant PROJECT-NAME permission
  > View and modify but not delete your email

  -> Allow
  > Confirm your choices

  -> Allow

## Feedbacks and contributions

Bugs, issues and contributions can be requested on the [official Github project][gmailtools].
When reporting issues, please provide the python version, command-line options
used, logs/errors, and the steps to reproduce the error.

## Requirements & dependencies

* Python v3.7+
* google-auth-oauthlib		0.0.4
* google-api-python-client	1.12.3

## References

1. A good summary of the label inheritance mis-feature on
[this StackExchange thread](https://webapps.stackexchange.com/questions/74238/how-do-i-work-around-labels-being-applied-to-individual-messages-and-not-convers)
1. A tutorial on how to [setup Gmail API](https://blog.mailtrap.io/send-emails-with-gmail-api/#How_to_make_your_app_send_emails_with_Gmail_API) and obtain the needed credentials.

