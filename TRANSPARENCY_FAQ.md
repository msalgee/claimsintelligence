## Claims Intelligence: Responsible AI FAQ 

- ### What is Claims Intelligence? 

  Claims Intelligence is an open-source GitHub repository that extracts data from unstructured documents and transforms it into defined schemas with validation, to enhance the speed of downstream data ingestion and improve quality. It enables the ability to efficiently automate extraction, validation, and structuring of information for event-driven system-to-system workflows. The project is built using Azure OpenAI Service, Azure AI Services, Azure AI Content Understanding Service, Azure Cosmos DB, and Azure Container Apps.  

 

- ### What can Claims Intelligence do?  

    The sample solution is tailored for a Claims Specialist at an auto insurance company, who reviews large amounts of claim-related data including forms, reports, repair estimates, and damage photos. The sample data is synthetically generated utilizing Azure OpenAI Service and saved into related templates and files, which are unstructured documents that can be used to show the processing pipeline. Any names and other personally identifiable information in the sample data is fictitious.  

    The sample solution processes the uploaded documents by exposing an API endpoint that utilizes Azure OpenAI Service and Azure AI Content Understanding Service for extraction. The extracted data is then transformed into a specific schema output based on the content type (ex: repair estimate), and validates the extraction and schema mapping through accuracy scoring. The scoring enables thresholds to dictate a human-in-the-loop review of the output if needed, allowing a user to review, update, and add comments. The solution also summarizes and identifies gaps across the collection of uploaded documents.

    Beyond per-document extraction, the solution runs a claim-level orchestration pipeline (Microsoft Agent Framework) that includes:
    - **Responsible AI safety gate** — every claim's consolidated content is screened by Azure AI Content Safety before downstream summarization or recommendation steps are allowed to run. Claims that fail the safety gate are surfaced to a human reviewer rather than being auto-summarized.
    - **AI summary** — a concise multi-document summary intended only as decision support for a human claims professional.
    - **Gap analysis** — a YAML-DSL ruleset evaluates the claim against configurable business rules and produces a list of missing or inconsistent items for the reviewer.
    - **Policy-grounded recommendation** — the recommendation agent grounds its output in two distinct sources: (1) member auto-policy contracts (authoritative source of coverage, deductibles, endorsements, and policy status, retrieved by exact policy-number match) and (2) a corpus of claims-handling guidance and procedure documents (advisory, retrieved semantically). Recommendations cite the specific policy clauses and guidance passages used so reviewers can verify the basis of any suggested action.

- ### What is/are Claims Intelligence's intended use(s)? 

    This repository is intended for use as an experimental sample, following the open-source license terms listed in the GitHub repository. The example scenario's intended purpose is to demonstrate how users can extract data from unstructured content to enhance the speed of data ingestion, transformation to pre-defined schemas, and improve data quality for downstream processing. The output is for informational purposes only and should be reviewed by a human. 


- ### How was Claims Intelligence evaluated? What metrics are used to measure performance? 

  The sample solution was evaluated using Azure AI Foundry Prompt Flow to test for harmful content, groundedness, and potential security risks.  

- ### What are the limitations of Claims Intelligence? How can users minimize the project's limitations when using the system?   

  This project is provided only as a sample to accelerate the creation of content-processing solutions. The repository showcases a sample scenario of a Claims Specialist at an auto insurance company, analyzing large amounts of claim-related data, but a human must still be responsible for validating the accuracy and correctness of data extracted from their documents, schema definitions related to business-specific documents to be extracted, quality and validation scoring logic and thresholds for human-in-the-loop review, ingesting transformed data into subsequent systems, and their relevancy for use with customers. Users of this project should review the system prompts provided and update them per their organizational guidance. 
  
  AI generated content in the solution may be inaccurate and the outputs and integrated solutions derived from the output data are not robustly trustworthy and should be manually reviewed by the user. You can find more information on AI generated content accuracy at https://aka.ms/overreliance-framework.

  The Responsible AI safety gate uses Azure AI Content Safety with default thresholds and is not a substitute for human review. The policy-grounded recommendation agent retrieves member-policy contracts and claims-handling guidance from user-supplied AI Search indexes — the quality of recommendations is bounded by the completeness, accuracy, and currency of the indexed content. Anyone using this project with their own policy and guidance content is responsible for validating that the indexes reflect current policy and procedure and for monitoring agent outputs.

  Currently, the sample repository is available in English only and is only tested to support PDF, PNG, and JPEG files up to 20MB in size.

- ### What operational factors and settings allow for effective and responsible use of Claims Intelligence? 

    Users can try different values for some parameters, including but not limited to system prompt, temperature, and max tokens shared as configurable environment variables while running evaluations during content processing. Schema definitions can and should be customized by the user to match specific business data definitions. Please note that these parameters are only provided as guidance to start the configuration but not as a complete available list to adjust the system behavior. Users should adjust the system to meet their needs. Please always refer to the latest product documentation for these details.