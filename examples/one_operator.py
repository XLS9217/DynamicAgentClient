"""
uv run -m dynamic_agent_client.examples.one_operator
"""
import asyncio
import json
import sys
import math
import random
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from dynamic_agent_client import DynamicAgentClient, AgentOperator, agent_tool, description, flow


class MathOperator(AgentOperator):

    @description
    def math_description(self) -> str:
        return "A math operator that performs vector operations."

    @flow
    def math_flow(self) -> str:
        return "1. Receive two vectors\n2. Compute the requested operation\n3. Return the result"

    @flow
    def triangle_normal_angle(self) -> str:
        return "1. Use cross product to compute normal vector for each triangle\n2. Compute magnitude of each normal vector\n3. Compute dot product of the two normal vectors\n4. Divide dot product by (magnitude_a * magnitude_b) to get cosine\n5. Use arccosine to get the angle in degrees"

    @agent_tool(description="Compute dot product of two vectors")
    def dot_product(self, vector_a: list[float], vector_b: list[float]) -> float:
        """
        :param vector_a: The first vector
        :param vector_b: The second vector
        """
        # print(f"dot_product Received vectors: {vector_a} and {vector_b}")
        if len(vector_a) != len(vector_b):
            raise ValueError("Vectors must be the same length for dot product")
        return sum(a * b for a, b in zip(vector_a, vector_b))

    @agent_tool(description="Compute cross product of two 3D vectors")
    def cross_product(self, vector_a: list[float], vector_b: list[float]) -> list[float]:
        """
        :param vector_a: The first 3D vector
        :param vector_b: The second 3D vector
        """
        # print(f"cross_product Received vectors: {vector_a} and {vector_b}")
        if len(vector_a) != 3 or len(vector_b) != 3:
            raise ValueError(f"Cross product requires 3D vectors input is {vector_a} and {vector_b}")
        a1, a2, a3 = vector_a
        b1, b2, b3 = vector_b
        return [
            a2 * b3 - a3 * b2,
            a3 * b1 - a1 * b3,
            a1 * b2 - a2 * b1,
        ]

    @agent_tool(description="Compute the magnitude (length) of a vector")
    def magnitude(self, vector: list[float]) -> float:
        """
        :param vector: The vector
        """
        # print(f"magnitude Received vector: {vector}")
        return math.sqrt(sum(x * x for x in vector))

    @agent_tool(description="Compute arccosine of a value, returns angle in degrees")
    def arccos(self, value: float) -> float:
        """
        :param value: The cosine value (between -1 and 1)
        """
        # print(f"arccos Received value: {value}")
        return math.degrees(math.acos(value))


def generate_cross_then_dot_example():
    """Returns (prompt, expected_answer)."""
    op = MathOperator()
    a = [round(random.uniform(-10, 10), 3) for _ in range(3)]
    b = [round(random.uniform(-10, 10), 3) for _ in range(3)]
    c = [round(random.uniform(-10, 10), 3) for _ in range(3)]

    cross = op.cross_product(a, b)
    dot = op.dot_product(cross, c)

    prompt = f"Calculate the cross product of {a} and {b}, then calculate the dot product of the result and {c}. respond the answer directly"
    return prompt, dot


def generate_triangle_example():
    """
    Generate two random triangles and compute the angle between their normals.
    Returns (prompt, expected_angle_in_degrees).
    """
    op = MathOperator()

    def rand_point():
        return [round(random.uniform(-10, 10), 3) for _ in range(3)]

    def vec_sub(p, q):
        return [p[i] - q[i] for i in range(3)]

    a0, a1, a2 = rand_point(), rand_point(), rand_point()
    b0, b1, b2 = rand_point(), rand_point(), rand_point()

    normal_a = op.cross_product(vec_sub(a1, a0), vec_sub(a2, a0))
    normal_b = op.cross_product(vec_sub(b1, b0), vec_sub(b2, b0))

    dot = op.dot_product(normal_a, normal_b)
    mag_a = op.magnitude(normal_a)
    mag_b = op.magnitude(normal_b)
    cos_val = max(-1.0, min(1.0, dot / (mag_a * mag_b)))
    angle = op.arccos(cos_val)

    prompt = (
        f"Given triangle A with vertices {a0}, {a1}, {a2} "
        f"and triangle B with vertices {b0}, {b1}, {b2}, "
        f"find the angle between their normal vectors in degrees.respond the answer directly"
    )
    return prompt, angle


async def main():
    port = os.getenv("PORT", "7777")

    # 1. Connect to the service
    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    # 2. Create a session
    client = await DynamicAgentClient.create(setting="You are a helpful math assistant.")
    print(f"Session created: {client.session_id}")

    # 2. Register the MathOperator
    op = MathOperator()
    result = await client.add_operator(op)
    print(f"Operator registered: {result}")

    def on_invoke(text: str):
        print(text)

    # 3. Test cross then dot
    prompt, expected = generate_cross_then_dot_example()
    response = await client.trigger(prompt, on_invoke=on_invoke)
    print(f"Prompt: {prompt}")
    print(f"Expected: {expected}")
    print(f"Response: {response}\n")

    # 4. Test triangle normal angle
    prompt, expected = generate_triangle_example()
    response = await client.trigger(prompt, on_invoke=on_invoke)
    print(f"Prompt: {prompt}")
    print(f"Expected: {expected}")
    print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(main())
