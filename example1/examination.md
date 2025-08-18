Create a multi-channel forum api. Can use any stack, but must use typescript, be deployable, and of production quality.
Try using graphql or grpc for fun, but REST is ok too.
Try using docker containers for fun if you want.
Show how you would like to write documentation and testing if possible.

Channel Model: { id, name }

Message Model: { id, title, content, channel, createdAt }

The API should have these features.

- create a channel
- write messages in a channel
- list messages in a channel and order by descending (pagination is a extra credit)

Show how a production level project would look. (documentation, testing, error handling, etc ...)

Send the repository link of the project by email when finished.