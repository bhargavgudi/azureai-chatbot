const messageBox =
    document.getElementById("message");

const chat =
    document.getElementById("chat");

const sendButton =
    document.getElementById("sendButton");


function addMessage(
    message,
    type
) {

    const container =
        document.createElement("div");

    container.className =
        `message ${type}`;


    const avatar =
        document.createElement("div");

    avatar.className =
        "avatar";

    avatar.innerText =
        type === "user"
            ? "You"
            : "AI";


    const bubble =
        document.createElement("div");

    bubble.className =
        "bubble";

    bubble.innerText =
        message;


    container.appendChild(
        avatar
    );

    container.appendChild(
        bubble
    );


    chat.appendChild(
        container
    );


    chat.scrollTop =
        chat.scrollHeight;
}


async function sendMessage() {

    const message =
        messageBox.value.trim();


    if (!message) {
        return;
    }


    addMessage(
        message,
        "user"
    );


    messageBox.value = "";

    sendButton.disabled =
        true;

    sendButton.innerText =
        "...";


    try {

        const response =
            await fetch(
                "/chat",
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        message: message
                    })

                }
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const data =
            await response.json();


        addMessage(
            data.response,
            "assistant"
        );


    } catch (error) {

        addMessage(
            "Sorry, something went wrong: "
            + error.message,
            "assistant"
        );

    } finally {

        sendButton.disabled =
            false;

        sendButton.innerText =
            "Send";

        messageBox.focus();

    }

}


messageBox.addEventListener(
    "keydown",
    function(event) {

        if (
            event.key === "Enter"
            &&
            !event.shiftKey
        ) {

            event.preventDefault();

            sendMessage();

        }

    }
);