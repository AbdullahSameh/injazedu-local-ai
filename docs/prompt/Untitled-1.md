I create this plan `docs/plan/core/injazedu-local-ai-code-agent-implementation-plan.md` with GPT with this prompt:

"
I want to create a Local AI project and train on it using [injazedu.co](http://injazedu.co/) as an application and benefit from it.

First: What is injazedu and what does it offer?

1. A platform specializing in providing professional license courses for male and female teachers, specifically for Qiyas tests in Saudi Arabia.
2. There is a section for STEP and IELTS courses and tests.
3. The platform works with or employs Trainers on a commission basis to deliver the courses.
4. The courses offered in each specialization consist of live lectures on Zoom or recorded lectures, along with a textbook for the subject matter and course-specific tests.
5. The lectures, textbook, and tests can only be viewed after registering for the course.
6. Some general tests are available to everyone, including those who are not registered.
7. Recorded lectures are available on [bunny.net](http://bunny.net/).
8. There is a Moderation Team for WhatsApp, Telegram, TikTok, and an Admin dashboard.
9. Trainers have a dashboard for monitoring and creating tests, both general and course-specific.
10. We have a Moderation team that sometimes assists Trainers in their work.

---

After reviewing with the injazedu team, we want to utilize AI by:

1. The courses contain textbooks in Word/PDF documents that explain the course content and include questions without answers specific to the course.
2. We want to use Word documents to create tests, both general and course-specific, similar to Qiyas tests if possible. (Note: that the test questions should be multiple-choice only).
3. Test creation will be done by the Moderation team or Trainers using AI. For example, we could use AI to generate about 5 tests per day from the course textbook, each consisting of approximately 20 to 30 questions, and suggest the correct answers. Of course, we won't publish the test until it's reviewed.  Or we could create the tests with the questions but display the correct answer as NULL. After review by the Moderation team, they will determine the correct answer in conjunction with the Trainer.
4. The ability to publish tests on Telegram by enabling and activating workflows and n8n from the Moderation team.
5. Researching ways to use workflows and n8n in customer service on Telegram and WhatsApp, and creating workflows that facilitate interaction.

---

- ​​We want to consider how to leverage AI and implement this, and what architecture and technology are required for implementation.
- I've attached a course books in `docs/textbooks` and also my Injazedu schema in `docs/schema` for the main and actual project, which is a MySQL schema. Also you can find the Injazedu project in `injazedu`.
- I need to know how the AI ​​will handle the books and how to divide them.
- I need to create a panel to control the parts of the AI ​​project, such as workflows, and how to divide them, etc. (Please specify which parts require a UI.)
- How will the main Injazedu project communicate with the local AI project, since they will each be on a different server?

Note about the execution environment:
- I will be running it locally on my Mac M1 Pro with 16GB of RAM.
- I will be using Ollama for my AI models. Please clarify which models you need. I currently have `gemma4\:e2b-it-qat` and `embeddinggemma:300m-qat-q4\_0`.
- I need the architecture to be compatible with switching from Ollama to vLLM or something similar.
"


I need you to review the plan carefully and what you think about it. Then finally create a final version of the plan with all the details and steps needed to implement the Local AI project for Injazedu.

You will create a final version only, without implementation, in `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`

Please ensure that the plan is clear and structured, and that it includes all necessary technical specifications, workflows, and UI requirements. Additionally, provide recommendations for any improvements or considerations to take into account during implementation.

Please ask me any questions for clarification or if anything is unclear or misunderstood.

Very important note:
It is not allowed to do anything in this `injazedu` directory; it is read-only.