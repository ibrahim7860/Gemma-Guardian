# Corrective Re-Prompts (verbatim)

These are appended on validation failure. Format strings; substitute the named fields.

## Wrapper

```
Your previous response was rejected because: {failure_reason}

{specific_corrective_prompt}

Try again. Call exactly one function.
```

## Specific corrective prompts

### severity_confidence_mismatch
You reported a severity {severity} finding with confidence {conf}. For severity 4 or higher, confidence must be at least 0.6. Either lower the severity or increase confidence with stronger visual evidence, or use continue_mission() if you are uncertain.

### gps_outside_zone
You reported a finding at GPS ({lat}, {lon}) but your assigned zone bounds are {bounds}. The finding must be within your zone. Either correct the coordinates if you mistyped, or use continue_mission() if the target is outside your zone.

### duplicate_finding
You reported a {type} at this location {seconds_ago} seconds ago. Do not duplicate findings. If this is a different target, describe the difference. Otherwise call continue_mission().

### visual_description_too_short
Your visual description was too short or empty. Provide at least 10 characters describing what you see in the image that supports this classification.

### invalid_function_name
You called a function that does not exist. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission. Call exactly one of these.

### prose_instead_of_function
You returned prose instead of a function call. You must call exactly one function. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission.

### coverage_decreased
You reported coverage of {new}% but previously reported {old}%. Coverage cannot decrease. Provide a coverage value greater than or equal to {old}%.

### invalid_argument_type
The arguments for {function} did not match the schema: {schema_error}. Fix the arguments and retry.

### return_to_base_low_battery_invalid
You called return_to_base(reason="low_battery") but your battery is at {battery}% which is above the 25% threshold. Use a different reason or continue_mission().

### return_to_base_mission_complete_invalid
You called return_to_base(reason="mission_complete") but you have {remaining} survey points still pending. Complete them or use a different reason.
