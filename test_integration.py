import asyncio
import os
from database import init_db, opt_in_user, is_user_opted_in, add_message, get_relevant_messages, forget_user
from router import AIRouter

async def test_all():
    print("--- Starting Integration Test ---")

    # Initialize DB
    init_db()
    print("1. Database initialized.")

    # Test User ID
    user_id = 123456789

    # 1. Test Opt-in
    print(f"2. Testing opt-in for user {user_id}...")
    opt_in_user(user_id)
    assert is_user_opted_in(user_id) == True
    print("   Opt-in successful.")

    # 2. Test Add Message
    print("3. Testing add_message...")
    messages = [
        "I really think that pizza with pineapple is a crime against humanity.",
        "Honestly, the best way to code is with a cup of coffee and some lo-fi music.",
        "Does anyone else feel like Discord bots are becoming self-aware?",
        "I love hiking on the weekends, it's so peaceful in the mountains.",
        "Python is definitely the most versatile language for AI development."
    ]
    for msg in messages:
        add_message(user_id, msg)
    print(f"   Added {len(messages)} messages.")

    # 3. Test Retrieval
    print("4. Testing get_relevant_messages (semantic search)...")
    relevant = get_relevant_messages(user_id, "tell me about food and cooking", limit=2)
    print(f"   Query: 'food and cooking' -> Result: {relevant}")
    # Should probably find the pizza message
    assert any("pizza" in msg.lower() for msg in relevant)

    relevant_coding = get_relevant_messages(user_id, "programming and software", limit=2)
    print(f"   Query: 'programming and software' -> Result: {relevant_coding}")
    # Should find the Python or code message
    assert any("python" in msg.lower() or "code" in msg.lower() for msg in relevant_coding)
    print("   Semantic search successful.")

    # 4. Test Token Counting
    print("5. Testing AIRouter token counting...")
    router = AIRouter()
    prompt = f"User Examples:\n" + "\n".join(messages) + "\nTopic: Food"
    tokens = router.count_tokens(prompt)
    print(f"   Prompt tokens: {tokens}")
    assert tokens > 0
    print("   Token counting successful.")

    # 5. Test Forget-Me
    print("6. Testing forget_user...")
    forget_user(user_id)
    assert is_user_opted_in(user_id) == False
    assert get_relevant_messages(user_id, "pizza") == []
    print("   Forget-me successful.")

    print("--- Integration Test Completed Successfully ---")

if __name__ == "__main__":
    asyncio.run(test_all())
