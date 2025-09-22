from datetime import datetime
from json import tool
from google import genai
from google.genai import types
from google.adk.tools import ToolContext
from google.cloud import storage
from . import config


client = genai.Client(
    vertexai=False,
)


async def generate_images(tool_context: ToolContext, imagen_prompt: str, product_artifact: str, asset_artifact: str) -> dict:
    try:   
        print(f"generate_images called with prompt: {imagen_prompt}, product_artifact: {product_artifact}, asset_artifact: {asset_artifact}")
         
        product_image: types.Part | None = await tool_context.load_artifact(filename=product_artifact)
        asset_image: types.Part | None = await tool_context.load_artifact(filename=asset_artifact)
        
        if product_image is None:
            print(f"Product image artifact '{product_artifact}' not found.")
            return {"status": "error", "message": f"Product image artifact '{product_artifact}' not found."}
        if asset_image is None:
            print(f"Asset image artifact '{asset_artifact}' not found.")
            return {"status": "error", "message": f"Asset image artifact '{asset_artifact}' not found."}

        # Create the chat
        chat = client.chats.create(model="gemini-2.5-flash-image-preview")
        # Send the image and ask for it to be edited
        response = chat.send_message(message=[imagen_prompt, product_image, asset_image])

        # Get the text and the image generated
        for i, part in enumerate(response.candidates[0].content.parts):
            if part.text is not None:
                print(part.text)
            elif part.inline_data is not None:
                # Get the image bytes
                image_bytes = part.inline_data.data
                counter = str(tool_context.state.get("loop_iteration", 0))
                artifact_name = f"generated_image_" + counter + ".jpg"
                # call save to gcs function
                if config.GCS_BUCKET_NAME:
                    save_to_gcs(tool_context, image_bytes, artifact_name, counter)
                
                try:    
                    # Save image to local disk
                    output_dir = "."
                    output_path = f"{output_dir}/{artifact_name}"
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                    print(f"Image also saved to disk: {output_path}")
                    tool_context.state["generated_image_local_path_" + counter] = output_path
                except Exception as e_disk:
                    print(f"Failed to save image to disk: {e_disk}")

                # Save as ADK artifact (optional, if still needed by other ADK components)
                report_artifact = types.Part.from_bytes(
                    data=image_bytes, mime_type="image/jpeg"
                )

                await tool_context.save_artifact(artifact_name, report_artifact)
                print(f"Image also saved as ADK artifact: {artifact_name}")

                tool_context.state["output_image"] = artifact_name

                return {
                    "status": "success",
                    "message": f"Image generated .  ADK artifact: {artifact_name}.",
                    "artifact_name": artifact_name,
                }
        else:
            # model_dump_json might not exist or be the best way to get error details
            error_details = str(response)  # Or a more specific error field if available
            print(f"No images generated. Response: {error_details}")
            return {
                "status": "error",
                "message": f"No images generated. Response: {error_details}",
            }

    except Exception as e:
        print(f"No images generated. Exception: {e}")
        return {"status": "error", "message": "No images generated.  {e}"}


def save_to_gcs(tool_context: ToolContext, image_bytes, filename: str, counter: str):
    # --- Save to GCS ---
    storage_client = storage.Client()  # Initialize GCS client
    bucket_name = config.GCS_BUCKET_NAME

    unique_id = tool_context.state.get("unique_id", "")
    current_date_str = datetime.utcnow().strftime("%Y-%m-%d")
    unique_filename = filename
    gcs_blob_name = f"{current_date_str}/{unique_id}/{unique_filename}"

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(gcs_blob_name)

    try:
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        gcs_uri = f"gs://{bucket_name}/{gcs_blob_name}"

        # Store GCS URI in session context
        # Store GCS URI in session context
        tool_context.state["generated_image_gcs_uri_" + counter] = gcs_uri

    except Exception as e_gcs:

        # Decide if this is a fatal error for the tool
        return {
            "status": "error",
            "message": f"Image generated but failed to upload to GCS: {e_gcs}",
        }
        # --- End Save to GCS ---
