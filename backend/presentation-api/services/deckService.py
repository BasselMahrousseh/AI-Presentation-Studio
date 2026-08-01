import asyncio
import os
from pathlib import Path
import httpx
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
    res= startJob(job.JOB_ID,prompt)
    slideSpecs = res["slide_specs"]

    slideSpecCollection = {
        "slides": [slide.model_dump() for slide in slideSpecs]      
    }

    # Create an output directory if it doesn't exist
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Save JSON file
    json_path = output_dir / f"{job.JOB_ID}_slide_specs.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(slideSpecCollection, f, indent=4)

    print(f"Saved JSON to: {json_path.resolve()}")
    # print(f"Slide Spec Collection: {json.dumps(slideSpecCollection, indent=2)}")
    ppt = sendRequestToPPTComposer(slideSpecCollection)

    return ppt
    # print(deck_brief)
    # return job

def getJobFromQueue(job_id):
    for job in db:
        if job.JOB_ID == int(job_id):
            return job
    return None

def startJob(job_id,prompt):
    job = getJobFromQueue(job_id)

    job.STATUS = "IN_PROGRESS"

    deck_brief = generate_deck_brief(prompt)
    # print(deck_brief.model_dump_json(indent=2))

    deck_plan = generate_deck_plan(deck_brief)
    # print(deck_plan.model_dump_json(indent=2))

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
- Describe the required text, tables, diagrams and callouts.
- Only use object types supported by the SlideSpec schema.

For diagram objects, you MUST include a "diagram_type".

The ONLY supported diagram types are:

1. "pipeline"

Required structure:

{{
    "diagram_type": "pipeline",
    "steps": [
        "Step 1",
        "Step 2",
        "Step 3"
    ]
}}

2. "grid"

Required structure:

{{
    "diagram_type": "grid",
    "items": [
        {{
            "use_case": "Enterprise Search",
            "technologies": [
                "Technology 1",
                "Technology 2",
                "Technology 3"
            ]
        }}
    ]
}}

Do not create any other diagram_type.

Do not create diagram objects without diagram_type.

Do not invent custom diagram structures such as:
- sections
- highlights
- axes
- components
- flows
- relationships
- trends

Only use the structures explicitly defined above.

The allowed SlideObject types are:
- text
- table
- diagram
- callout

Do not generate:
- chart
- image
- icon
- citation

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
    print(json.dumps(data, indent=2))
    return [
        SlideSpec.model_validate(slide)
        for slide in data["slides"]
    ]

def sendRequestToPPTComposer(slide_specs: list[SlideSpec]):
    # This function would send the slide_specs to the PPT Composer service
    # and return the generated PowerPoint file or a link to it.
    response = httpx.post(
        "http://localhost:4000/compose",
        json=slide_specs
    )

    response.raise_for_status()

    return response.content