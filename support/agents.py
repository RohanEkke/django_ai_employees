from openai import OpenAI
from django.conf import settings
from .tools import get_order_details, get_refund_history, check_dilevery_status, get_costumer_risk_profile
from .models import Conversation, AgentLog
import json
from .event_queue import publish, DONE



client = OpenAI(
    api_key= settings.OPENROUTER_API_KEY,
    base_url= settings.BASE_URL
)

# Support system prompt --> Mayas job discription
SUPPORT_SYSTEM_PROMPT = """
You are Maya, a customer support agent at CoolBreeze AC.
You help customers with issues related to their AC orders.


Your responsibilities:
- Always use your tools to gather facts before responding
- Check order details when customer mentions their order
- Check refund history before making any refund decisions
- Be empathetic but honest

Your personality:
- Friendly and professional
- Patient even when customer is angry
- Clear and concise in your replies
- No emojies

Important rules:
- Always check order details first before responding
- Never approve or deny a refund yourself
- If a refund decision is needed, immediately consult the manager tool.
- Wait for the manager tool's decision before replying.
- Never tell the customer that you will get back later.
- Since the manager responds instantly, always provide the manager's decision in the same reply.
- Never use bold text, bullet points or any markdown formatting. Plain text only.
- Keep replies concise and conversational. Maximum 3-4 sentences. No long paragraphs.
"""


MANAGER_SYSTEM_PROMPT = """
You are a senior support manager at CoolBreeze AC.
A support agent has escalated a customer case to you for a refund decision.

Your responsibilities:
- Review the case summary carefully
- Consider the customer's refund history
- Make a fair and final refund decision
- Give a clear reason for your decision

Your decision options:
- Approve refund — if the case is genuine and within policy
- Deny refund — if the case is suspicious or outside policy
- Escalate to risk team — if you suspect fraud

Important rules:
- Be fair but firm
- Base decision on facts — not emotions
- Always give a specific reason for your decision
- Keep your response concise and professional
"""


RISK_SYSTEM_PROMPT = """
You are a fraud risk analyst at CoolBreeze AC.
A support manager has sent you a customer profile for risk assessment.

Your job:
- Analyse the customer's order and refund patterns
- Identify suspicious behaviour
- Return a clear risk verdict

Risk levels:
- LOW — genuine customer, normal behaviour
- MEDIUM — some suspicious signals, proceed with caution
- HIGH — clear fraud pattern, recommend denial

Your response format:
- Risk Level: LOW / MEDIUM / HIGH
- Key Signals: what you found suspicious or genuine
- Recommendation: what manager should do

Important:
- Be objective — base verdict on data only
- One bad refund does not make someone fraudulent
- Look for patterns — not isolated incidents
"""


# Antropic Support tools --> Tool schemas that ai agent will read
ANTROPIC_SUPPORT_TOOLS = [
    {
        "name" : "get_order_details",
        "discription" : "Fetch complete order details including status, carrier, tracking number and date since order was placed. Use this when costumer mentions their order or complaints about dilevery.",
        "input_schema" : {
            "type" : "object",
            "properties" : {
                "order_id" : {
                    "type" : "integer",
                    "description" : "The order ID to look up"
                }
            },
            "required" : ["order_id"]
        }
    },

    {
        "name": "get_refund_history",
        "description": "Get complete refund history for a user. Use this before making any refund related decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to check refund history for"
                }
            },
            "required": ["user_id"]
        }
    },

    {
        "name": "check_delivery_status",
        "description": "Check current delivery status using tracking number and carrier. Use this when customer complains about delayed or missing delivery.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "The shipment tracking number"
                },
                "carrier": {
                    "type": "string",
                    "description": "The carrier name for example BlueDart or Delhivery"
                }
            },
            "required": ["tracking_number", "carrier"]
        }
    },

    {
        "name": "escalate_to_manager",
        "description": "Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "case_summary": {
                    "type": "string",
                    "description": "Complete case summary. Must include: customer user_id, order details, refund history and complaint. Format: Start with 'Customer User ID: X' on the first line."
                }
            },
            "required": ["case_summary"]
        }
    }

    
]

MANAGER_TOOLS = [
    {
        "name": "assess_fraud_risk",
        "description": "Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess fraud risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]



# risk tool in antropic format
RISK_TOOLS = [
    {
        "name": "get_customer_risk_profile",
        "description": "Get complete risk profile for a customer including order history, refund patterns and ratio. Use this to assess fraud risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]


# support tool for openai format
OPENAI_SUPPORT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": "Fetch complete order details including status, carrier, tracking number and date since order was placed. Use this when the customer mentions their order or complains about delivery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "integer",
                        "description": "The order ID to look up"
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_refund_history",
            "description": "Get complete refund history for a user. Use this before making any refund-related decisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The user ID to check refund history for"
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_dilevery_status",
            "description": "Check current delivery status using tracking number and carrier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tracking_number": {
                        "type": "string",
                        "description": "The shipment tracking number"
                    },
                    "carrier": {
                        "type": "string",
                        "description": "The carrier name, e.g. BlueDart or Delhivery"
                    }
                },
                "required": ["tracking_number", "carrier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_manager",
            "description": "Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_summery": {
                        "type": "string",
                        "description": "Complete case summary. Must include: customer user_id, order details, refund history and complaint. Format: Start with 'Customer User ID: X' on the first line."
                    }
            },
            "required": ["case_summery"]
            }
        }
    }
]

OPENAI_MANAGER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "assess_fraud_risk",
            "description": "Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The user ID to assess fraud risk for"
                    }
                },
                "required": ["user_id"]

            }


        }
    }
    
]

OPENAI_RISK_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_costumer_risk_profile",
            "description": "Get complete risk profile for a customer including order history, refund patterns and ratio. Use this to assess fraud risk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The user ID to assess risk for"
                    }
                },
                "required": ["user_id"]

            }
        }
    }
]



# execute_tool() --> Bridge between openai and python program (tools).
def execute_tool(tool_name, tool_input, conversation_id=None):
    tool_input = json.loads(tool_input)
    if tool_name == "get_order_details" :
        return get_order_details(tool_input["order_id"])
    
    if tool_name == "get_refund_history" :
        return get_refund_history(tool_input["user_id"])
    
    if tool_name == "check_dilevery_status" :
        return check_dilevery_status(tool_input["tracking_number"], tool_input["carrier"])

    if tool_name == "escalate_to_manager" :
        case_summery = tool_input["case_summery"]
        print("escalating to manager ====>", case_summery)
        decision = run_manager_agent(case_summery, conversation_id)
        print("dicision ====>", decision)
        return decision
    
    if tool_name == "assess_fraud_risk":
        user_id = tool_input['user_id']
        print("conselting for risk for user =====>", user_id)
        verdict = run_risk_agent(user_id, conversation_id)
        print("verdict =====>", verdict)
        return verdict

    if tool_name == "get_costumer_risk_profile":
        return get_costumer_risk_profile(tool_input["user_id"])












# Agent loop --> while loop until the task is done.

def run_support_agent(user_message, conversation_id, order_id, user_id):
    conv = Conversation.objects.get(id=conversation_id)

    conversation_messages = []
    for msg in conv.messages.order_by("created_at"):
        conversation_messages.append({
            "role": msg.role,
            "content": msg.content
        })

    # send this conversation to llm
    messages=[
            {"role": "system", 
             "content": f"{SUPPORT_SYSTEM_PROMPT}\n\nThis conversation is about user id: {user_id} and order id: {order_id}"
            },
            *conversation_messages
        ]
    # print("messages ==>", messages)
    while True:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages,
            tools=OPENAI_SUPPORT_TOOLS,
        )

        message = response.choices[0].message

        if not message.tool_calls:
            # publish final event
            final_reply = message.content
            event = {"type": "final", "message": final_reply}
            publish(conversation_id, event)
            # log final reply
            AgentLog.objects.create(conversation=conv, event_type="final", message=final_reply)
            publish(conversation_id, DONE)

            return final_reply

        # Add assistant message containing tool calls
        messages.append(message)

        for tool_call in message.tool_calls:
            event = {"type":"tool_call", "message":f"Calling tool {tool_call.function.name} with {tool_call.function.arguments}"}
            publish(conversation_id, event)
            # log tool call
            AgentLog.objects.create(conversation=conv, event_type="tool_call", message=f"Calling tool {tool_call.function.name} with {tool_call.function.arguments}")


            # execute the tool
            result = execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                conversation_id
            )

            event = {"type":"tool_result", "message":f"{tool_call.function.name} returned: {json.dumps(result)[:200]}"}
            publish(conversation_id, event)

            # log tool result
            AgentLog.objects.create(conversation=conv, event_type="tool_result", message=f"{tool_call.function.name} returned: {json.dumps(result)[:200]}")

            print("Support agent tool called ==========>",  tool_call.function.name)
            print("Support agent tool inputed =============>", tool_call.function.arguments)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result)
            })




        
def run_manager_agent(case_summery, conversation_id):
    conv = Conversation.objects.get(id=conversation_id)
    event = {"type":"manager", "message":f"Case recived for review: {case_summery[:200]}"}
    publish(conversation_id, event)

    AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Case recived for review: {case_summery[:200]}")
    manager_messages = [
        {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
        {"role": "user", "content": case_summery}, # user is task giver (agent Maya)
        
    ]

    while True:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=manager_messages,
            max_tokens=1020,
            tools=OPENAI_MANAGER_TOOL
        )

        message = response.choices[0].message

        if not message.tool_calls:
            event = {"type":"manager", "message":message.content}
            publish(conversation_id, event)
            
             # log manager desigion
            AgentLog.objects.create(conversation=conv, event_type="manager", message=message.content)
            return message.content
        
        manager_messages.append(message)


        for tool_call in message.tool_calls:
            event = {"type":"manager", "message":"Consulting risk agent for fraud assessment..."}
            publish(conversation_id, event)
            

            # log consulting risk agent
            AgentLog.objects.create(conversation=conv, event_type="manager", message="Consulting risk agent for fraud assessment...")
            
            result = execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                conversation_id
            )
            print("manager agent tool called ==========>",  tool_call.function.name)
            print("manager agent tool inputed =============>", tool_call.function.arguments)

            manager_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result)
            })
       

        



       
def run_risk_agent(user_id, conversation_id):
    conv= Conversation.objects.get(id=conversation_id)
    event = {"type":"risk", "message":f"Starting fraud assessment for {user_id}"}
    publish(conversation_id, event)

    AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Starting fraud assessment for {user_id}")
    risk_messages = [
        {"role": "system", "content": RISK_SYSTEM_PROMPT},
        {"role": "user", "content": f"Please assess the fraud risk for user ID {user_id}. User your tool to get their profile and return a verdict."}
    ]

    while True:

        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=risk_messages,
            max_tokens=1020,
            tools=OPENAI_RISK_TOOL
        )

        message = response.choices[0].message

        if not message.tool_calls:
            event = {"type":"risk", "message":f"Verdict: {message.content}"}
            publish(conversation_id, event)

            AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Verdict: {message.content}")

            return message.content
        
        risk_messages.append(message)

        for tool_call in message.tool_calls:
            event = {"type":"risk", "message":f"Calling {tool_call.function.name} for customer risk profile"}
            publish(conversation_id, event)

            AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Calling {tool_call.function.name} for customer risk profile")

            result = execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                conversation_id
            )
            print("risk agent tool called ==========>",  tool_call.function.name)
            print("risk agent tool inputed =============>", tool_call.function.arguments)

            risk_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result)
            })



    





    