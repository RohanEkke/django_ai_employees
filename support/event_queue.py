import queue


subscribers = {} # {25:[queue_1, queue2], 24:[queue_1]} {conversation id: numbers of queue (viewing the pannel)}


def subscribe(conversation_id):
    q = queue.Queue() # create empety queue for this browser tab

    if conversation_id not in subscribers:
        subscribers[conversation_id] = []

    subscribers[conversation_id].append(q)
    return q


def unsubscribe(conversation_id, q):
    if conversation_id in subscribers:
        subscribers[conversation_id].remove()
        if not subscribers[conversation_id]:
            del subscribers[conversation_id]
    


def publish(conversation_id, event):
    print(f"Publishing to conversation {conversation_id}: {event}")
    if conversation_id in subscribers:
        for q in subscribers[conversation_id]:
            q.put(event)
    

# sentinal value - it tell sse to stop
DONE = {"type":"done"}