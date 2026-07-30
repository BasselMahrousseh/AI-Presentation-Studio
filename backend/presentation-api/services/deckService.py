import asyncio
import os
from pathlib import Path

from input.inputClasses import DeckBrief, DeckPlan, SlideSpec
from openai import AzureOpenAI
from dotenv import load_dotenv
import json

load_dotenv(Path(__file__).resolve().parent / ".env")
db = []

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")




def addJobToQueue(job,prompt):
    db.append(job)
    print(f"Job added to queue: {job.JOB_ID}")
    # asyncio.create_task(startJob(job.JOB_ID))
    deck_brief = startJob(job.JOB_ID,prompt)
    # print(deck_brief)
    return job

def getJobFromQueue(job_id):
    for job in db:
        if job.JOB_ID == int(job_id):
            return job
    return None

def startJob(job_id,prompt):
    job = getJobFromQueue(job_id)

    job.STATUS = "IN_PROGRESS"

    deck_brief = generate_deck_brief(prompt)
    print(deck_brief.model_dump_json(indent=2))

    deck_plan = generate_deck_plan(deck_brief)
    print(deck_plan.model_dump_json(indent=2))

    slide_specs = generate_slide_specs(deck_plan)
    for slide in slide_specs:
        print(slide.model_dump_json(indent=2))

    job.STATUS = "COMPLETED"

    return {
        "deck_brief": deck_brief,
        "deck_plan": deck_plan,
        "slide_specs": slide_specs
    }


def generate_deck_brief(prompt: str) -> DeckBrief:
    print(os.getenv("AZURE_OPENAI_ENDPOINT"))
    print(f"Generating deck brief for prompt: {prompt}")
    response = client.chat.completions.create(
        model=deployment,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": f"""
You are an expert presentation planner. I need you to generate a deck brief for a presentation based on the following prompt. 
The output must be valid JSON and match the following structure:

Generate ONLY valid JSON matching this structure:

{DeckBrief.model_json_schema()}

Return JSON only.
"""
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    data = json.loads(response.choices[0].message.content)
    print(f"Finished Generating deck brief for prompt: {prompt}")

    return DeckBrief.model_validate(data)


def generate_deck_plan(deck_brief: DeckBrief) -> DeckPlan:
    print("Generating Deck Plan...")

    response = client.chat.completions.create(
        model=deployment,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": f"""
You are an expert presentation planner.

Your task is to convert the provided DeckBrief into a DeckPlan.

The DeckPlan should:
- Follow the requested slide count.
- Create a logical narrative.
- Assign an appropriate archetype to every slide.
- Produce a clear purpose and message for each slide.

Generate ONLY valid JSON matching this schema:

{DeckPlan.model_json_schema()}

Return ONLY JSON.
"""
            },
            {
                "role": "user",
                "content": deck_brief.model_dump_json(indent=2)
            }
        ]
    )

    data = json.loads(response.choices[0].message.content)

    print("Finished generating Deck Plan.")

    return DeckPlan.model_validate(data)


def generate_slide_specs(deck_plan: DeckPlan) -> list[SlideSpec]:
    print("Generating Slide Specs...")

    response = client.chat.completions.create(
        model=deployment,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": f"""
You are an expert PowerPoint designer.

Your task is to convert the DeckPlan into SlideSpec objects.

For every slide:
- Create a SlideSpec.
- Include semantic objects only.
- Do NOT include coordinates.
- Do NOT include pixel positions.
- Describe the required text, tables, diagrams, charts and images.

Return ONLY valid JSON.

The JSON should be an object with the following format:

{{
    "slides": [
        {SlideSpec.model_json_schema()}
    ]
}}
"""
            },
            {
                "role": "user",
                "content": deck_plan.model_dump_json(indent=2)
            }
        ]
    )

    data = json.loads(response.choices[0].message.content)

    print("Finished generating Slide Specs.")

    return [
        SlideSpec.model_validate(slide)
        for slide in data["slides"]
    ]