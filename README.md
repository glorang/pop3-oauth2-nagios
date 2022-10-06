# pop3-oauth2-nagios
Nagios plugin to check message count and age in an Office 365 POP3 mailbox using OAuth2 authentication.

This plugin implements the "OAuth 2.0 client credentials grant".

The popliboauth in this repository is a copy of Python 3.7's poplib with one function added for token authentication (`def oauth`).

It will only work against Microsoft Office 365.

# Token cache

The plugin will fetch a token and store it in `pop3-oauth2-nagios.tokens` as a token cache. By default tokens are valid for 1 hour.

Make sure this file is writable by your Nagios user and only readable by your Nagios user (chmod it 600 it once created).

# Plugin configuration

- Create Azure AD app and grant it POP.AccessAsApp permission + Grant it admin consent
- Setup `pop3-oauth2-nagios.cfg` as follows:

```
[general]
server = outlook.office365.com
tenant = <your tenant UUID>
scope = https://outlook.office365.com/.default

[mailbox1@domain.com]
clientid = <clientid>
secret = <secret>

[mailbox2@domain.com]
clientid = <clientid>
secret = <secret>
```

# Nagios config

`commands.cfg`:

```
define command {
  command_name    check_email_age_oauth
  command_line    /etc/nagios3/plugins/pop3-oauth2-nagios/pop3-oauth2-nagios.py -u $ARG1$ -w $ARG2$ -c $ARG3$
}
```

`services.cfg`:

```
define service {
        host_name               <host>
        service_description     POP3S: mailbox1@domain.com
        check_command           check_email_age_oauth!mailbox1@domain.com!1!2
        use                     generic-service
        notification_interval   0
}
```

# References

https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-client-creds-grant-flow
https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
https://www.limilabs.com/blog/oauth2-client-credential-flow-office365-exchange-imap-pop3-smtp
